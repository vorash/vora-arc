from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from vora import Sandbox, Stats, Vora, VoraError

from .model import BatchResult, Grid, GridResult, GridStatus, RunStatus, Task
from .profile import Profile

log = logging.getLogger(__name__)

RETRY_DELAYS_S: tuple[float, ...] = (0.5, 1.0, 2.0)
MAX_LINE_BYTES = 1 << 20

_RUN_STATUS_BY_EXIT_REASON: dict[str, RunStatus] = {
    "EXITED": RunStatus.COMPLETED,
    "TIMEOUT_EXCEEDED": RunStatus.KILLED_TIMEOUT,
    "OOM_KILLED": RunStatus.KILLED_OOM,
    "PIDS_LIMIT_EXCEEDED": RunStatus.POLICY_VIOLATION,
}

_UNREPORTED_INPUT_STATUS: dict[RunStatus, GridStatus] = {
    RunStatus.COMPLETED: GridStatus.ERROR,
    RunStatus.KILLED_TIMEOUT: GridStatus.TIMEOUT,
    RunStatus.KILLED_OOM: GridStatus.ERROR,
    RunStatus.POLICY_VIOLATION: GridStatus.ERROR,
}


class SandboxInfrastructureError(Exception):
    """Vora failed in a way that says nothing about the program."""


async def run_batch(
    vora: Vora,
    profile: Profile,
    program: str,
    task: Task,
    *,
    correlation_id: str,
) -> BatchResult:
    """Run ``program`` against every input of ``task`` in one fresh sandbox.

    Inputs are the train inputs (index 0..n-1), then the test inputs.
    """
    is_test = tuple([False] * len(task.train) + [True] * len(task.test))
    grids = [pair.input for pair in task.train] + [case.input for case in task.test]
    stdin = json.dumps(
        {
            "program": program,
            "inputs": [
                {"index": index, "is_test": is_test[index], "grid": [list(row) for row in grid]}
                for index, grid in enumerate(grids)
            ],
            "per_input_timeout_ms": profile.per_input_timeout_ms,
        }
    )
    delays = iter(RETRY_DELAYS_S)
    while True:
        try:
            run = await _run_once(vora, profile, stdin, is_test)
            break
        except (VoraError, httpx.TransportError) as error:
            delay = next(delays, None)
            if delay is None or not _is_transport_error(error):
                raise
            log.warning("%s: transport error, retrying in %ss: %s", correlation_id, delay, error)
            await asyncio.sleep(delay)

    run_status = _run_status(run.exec, run.stats)
    unreported = _UNREPORTED_INPUT_STATUS[run_status]
    results = tuple(
        run.exec.results.get(index)
        or GridResult(index, test, unreported, None, f"no result: the run ended {run_status}", 0)
        for index, test in enumerate(is_test)
    )
    done = run.exec.done
    stderr_tail = done.stderr_tail if done is not None else run.exec.stderr.decode("utf-8", "replace")
    return BatchResult(
        correlation_id=correlation_id,
        program_sha256=hashlib.sha256(program.encode("utf-8")).hexdigest(),
        run_status=run_status,
        grids=results,
        sandbox_id=run.sandbox_id,
        startup_ms=run.startup_ms,
        exec_ms=run.exec_ms,
        peak_mem_bytes=run.stats.memory_peak_bytes,
        cpu_ms=run.stats.cpu_millis,
        stderr_tail=_tail(stderr_tail, profile.output_tail_bytes),
    )


@dataclass(frozen=True)
class _Done:
    stderr_tail: str


@dataclass(frozen=True)
class _Exec:
    results: dict[int, GridResult]
    done: _Done | None
    exited: bool
    exit_reason: str | None
    stderr: bytes


@dataclass(frozen=True)
class _Run:
    sandbox_id: str
    startup_ms: int
    exec_ms: int
    exec: _Exec
    stats: Stats


async def _run_once(vora: Vora, profile: Profile, stdin: str, is_test: tuple[bool, ...]) -> _Run:
    started = time.monotonic()
    sandbox = await vora.sandboxes.create(
        image=profile.image,
        backend=profile.backend,
        network=profile.network,
        cpu=f"{profile.cpu_millis}m",
        memory=profile.memory_bytes,
        pids=profile.pids,
        ttl=profile.ttl_seconds,
    )
    startup_ms = _elapsed_ms(started)
    try:
        exec_started = time.monotonic()
        output = await _exec(sandbox, profile, stdin, is_test)
        exec_ms = _elapsed_ms(exec_started)
        try:
            stats = await sandbox.stats()
        except (VoraError, httpx.TransportError) as error:
            raise SandboxInfrastructureError(f"{sandbox.id}: stats after the run failed: {error}") from error
    finally:
        await _destroy(sandbox, profile)
    return _Run(sandbox.id, startup_ms, exec_ms, output, stats)


async def _exec(sandbox: Sandbox, profile: Profile, stdin: str, is_test: tuple[bool, ...]) -> _Exec:
    lines = _LineBuffer()
    results: dict[int, GridResult] = {}
    done: _Done | None = None
    stderr = bytearray()
    exited = False
    exit_reason: str | None = None
    started_streaming = False
    command, *args = profile.runner_command
    try:
        async for chunk in sandbox.stream_exec(
            command, args, stdin=stdin, timeout_seconds=profile.batch_timeout_seconds
        ):
            started_streaming = True
            if chunk.kind == "stdout":
                for line in lines.feed(chunk.data):
                    parsed = _parse_line(line, is_test)
                    if isinstance(parsed, _Done):
                        done = done or parsed
                    elif parsed is not None:
                        results.setdefault(parsed.index, parsed)
            elif chunk.kind == "stderr":
                stderr += chunk.data
                del stderr[: -profile.output_tail_bytes]
            else:
                exited, exit_reason = True, chunk.reason
    except (VoraError, httpx.TransportError) as error:
        # Once output arrived the program has run; running it again would retry a program.
        if started_streaming and _is_transport_error(error):
            raise SandboxInfrastructureError(f"{sandbox.id}: exec stream broke: {error}") from error
        raise
    return _Exec(results, done, exited, exit_reason, bytes(stderr))


def _run_status(output: _Exec, stats: Stats) -> RunStatus:
    # Vora's exec exit record only says EXITED or TIMEOUT_EXCEEDED. OOM and
    # pids-limit kills show up in the sandbox's cgroup counters, and an OOM
    # often takes the exec stream down with no exit record at all.
    if stats.oom_kills:
        reason: str | None = "OOM_KILLED"
    elif stats.pids_limit_hits:
        reason = "PIDS_LIMIT_EXCEEDED"
    elif output.exited:
        reason = output.exit_reason
    else:
        raise SandboxInfrastructureError("exec stream ended without an exit record and no resource kill")
    status = _RUN_STATUS_BY_EXIT_REASON.get(reason or "")
    if status is None:
        raise SandboxInfrastructureError(f"unexpected exit reason {reason!r}")
    return status


def _parse_line(line: bytes, is_test: tuple[bool, ...]) -> GridResult | _Done | None:
    """Parse one runner stdout line; anything that is not a protocol line is None."""
    if not line.startswith(b"{"):
        return None
    try:
        raw = json.loads(line)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("done") is True:
        tail = raw.get("stderr_tail")
        return _Done(tail) if isinstance(tail, str) else None
    index, error, wall_ms = raw.get("index"), raw.get("error"), raw.get("wall_ms")
    if type(index) is not int or not 0 <= index < len(is_test):
        return None
    if type(wall_ms) is not int or not (error is None or isinstance(error, str)):
        return None
    status = next((status for status in GridStatus if status.value == raw.get("status")), None)
    if status is None:
        return None
    output = _grid(raw.get("output")) if status is GridStatus.OK else None
    if status is GridStatus.OK and output is None:
        return None
    return GridResult(index, is_test[index], status, output, error, wall_ms)


def _grid(value: Any) -> Grid | None:
    if not isinstance(value, list) or not all(isinstance(row, list) for row in value):
        return None
    if not all(type(cell) is int for row in value for cell in row):
        return None
    return tuple(tuple(row) for row in value)


class _LineBuffer:
    """Splits a byte stream into lines, dropping any line over MAX_LINE_BYTES."""

    def __init__(self) -> None:
        self._pending = bytearray()
        self._skipping = False

    def feed(self, data: bytes) -> list[bytes]:
        *ended, rest = data.split(b"\n")
        lines: list[bytes] = []
        for part in ended:
            if not self._skipping:
                lines.append(bytes(self._pending + part))
            self._pending.clear()
            self._skipping = False
        if not self._skipping:
            self._pending += rest
            if len(self._pending) > MAX_LINE_BYTES:
                self._pending.clear()
                self._skipping = True
        return lines


def _is_transport_error(error: Exception) -> bool:
    if isinstance(error, httpx.TransportError):
        return True
    return isinstance(error, VoraError) and error.status is None and isinstance(error.__cause__, httpx.TransportError)


async def _destroy(sandbox: Sandbox, profile: Profile) -> None:
    try:
        await sandbox.destroy()
    except (VoraError, httpx.HTTPError):
        log.warning("destroy %s failed; its %ss TTL removes it", sandbox.id, profile.ttl_seconds, exc_info=True)


def _tail(text: str, limit: int) -> str:
    return text.encode("utf-8")[-limit:].decode("utf-8", "ignore")


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
