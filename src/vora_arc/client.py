from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar

import httpx
from vora import (
    Pool,
    PoolRun,
    PoolRunDone,
    PoolRunError,
    RateLimitedError,
    RunExit,
    Sandbox,
    Stats,
    UnavailableError,
    Vora,
    VoraError,
)

from .model import BatchResult, Grid, GridResult, GridStatus, RunStatus, Task
from .profile import Profile

log = logging.getLogger(__name__)

T = TypeVar("T")

RETRY_DELAYS_S: tuple[float, ...] = (0.5, 1.0, 2.0)
MAX_LINE_BYTES = 1 << 20
POOL_DELETE_WAIT_S = 60.0

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


class PoolMode(StrEnum):
    COLD = "cold"
    WARM = "warm"
    WARM_NO_RESET = "warm-no-reset"


@contextlib.asynccontextmanager
async def connect(profile: Profile) -> AsyncIterator[Vora]:
    """A Vora client for ``run_batch``, configured from VORA_API_URL and VORA_API_KEY."""
    # httpx's 5 s default read timeout is shorter than a batch that prints
    # nothing for 10 s, and a timeout would be retried as a transport error.
    timeout = httpx.Timeout(profile.batch_timeout_seconds + 30.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        yield Vora(client=http)


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
    stdin, is_test = batch_request(profile, program, task)
    run = await _retrying(correlation_id, lambda: _run_once(vora, profile, stdin, is_test))
    run_status = _run_status(run.exec, run.stats.oom_kills, run.stats.pids_limit_hits)
    return _batch_result(
        profile,
        program,
        is_test,
        correlation_id,
        run_status,
        run.exec,
        sandbox_id=run.sandbox_id,
        startup_ms=run.startup_ms,
        exec_ms=run.exec_ms,
        peak_mem_bytes=run.stats.memory_peak_bytes,
        cpu_ms=run.stats.cpu_millis,
        audit_log_id=run.exec.execution_id,
    )


def pool_shape(mode: PoolMode, concurrency: int) -> dict[str, Any]:
    """The spec fields that make a pool one of the experiment's arms. Nothing else differs."""
    if mode is PoolMode.COLD:
        # A retired member keeps its slot until its destroy returns. Twice the slots let the
        # next start overlap that destroy, so a cold run doesn't wait for the previous one's.
        # The client still runs only `concurrency` programs at a time.
        return {"size": 0, "max_size": 2 * concurrency}
    shape: dict[str, Any] = {"size": concurrency, "max_size": concurrency, "max_runs": 100}
    return shape | {"reuse": "unsafe_no_reset"} if mode is PoolMode.WARM_NO_RESET else shape


async def declare_pool(
    vora: Vora,
    profile: Profile,
    name: str,
    mode: PoolMode,
    concurrency: int,
    *,
    tenant_id: str | None = None,
    borrow_timeout_ms: int | None = None,
) -> Pool:
    return await vora.pools.declare(
        name,
        **pool_template(profile),
        tenant_id=tenant_id,
        borrow_timeout_ms=borrow_timeout_ms,
        **pool_shape(mode, concurrency),
    )


def pool_template(profile: Profile) -> dict[str, Any]:
    """A member's sandbox. A pool refuses every network mode but none, and a pids limit
    below its backend's floor, each with a 400 that says so. The TTL stays out, because
    a pool works out its members' own."""
    return {
        "image": profile.image,
        "backend": profile.backend,
        "network": profile.network,
        "cpu": f"{profile.cpu_millis}m",
        "memory": profile.memory_bytes,
        "pids": profile.pids,
    }


@contextlib.asynccontextmanager
async def open_pool(
    vora: Vora,
    profile: Profile,
    name: str,
    mode: PoolMode,
    concurrency: int,
    *,
    admin: Vora | None = None,
    tenant_id: str | None = None,
    borrow_timeout_ms: int | None = None,
) -> AsyncIterator[Pool]:
    """Declare a pool for this run, and delete it after: a live pool holds its capacity."""
    try:
        if mode is PoolMode.WARM_NO_RESET:
            # Only an admin may declare this shape. The runs still go through the tenant's key.
            if admin is None:
                raise SystemExit("the warm-no-reset arm needs an admin key: set VORA_ADMIN_API_KEY")
            await declare_pool(
                admin, profile, name, mode, concurrency, tenant_id=tenant_id, borrow_timeout_ms=borrow_timeout_ms
            )
            pool = await vora.pools.get(name)
        else:
            pool = await declare_pool(vora, profile, name, mode, concurrency, borrow_timeout_ms=borrow_timeout_ms)
    except VoraError as error:
        raise SystemExit(f"pool {name} was refused for profile {profile.name}: {error}") from error
    try:
        yield pool
    finally:
        try:
            await pool.delete(max_wait_seconds=POOL_DELETE_WAIT_S)
        except (VoraError, httpx.HTTPError):
            log.warning("delete pool %s failed; it keeps its capacity until deleted", name, exc_info=True)


async def pool_batch(pool: Pool, profile: Profile, program: str, task: Task, *, correlation_id: str) -> BatchResult:
    """Run ``program`` against every input of ``task`` on one member of ``pool``."""
    stdin, is_test = batch_request(profile, program, task)
    run = await _retrying(correlation_id, lambda: run_in_pool(pool, profile, stdin, is_test))
    return await pool_result(pool, profile, program, is_test, correlation_id, run)


@dataclass(frozen=True)
class PoolRunRecord:
    """What one pool run's stream said, before anyone judges it. Times are the client's."""

    run: PoolRun | None
    exit: RunExit | None
    done: PoolRunDone | None
    failure: PoolRunError | None
    """The stream broke after its first frame and before ``exit``, so the program may have run."""
    output: _Exec
    startup_ms: float | None
    """Request sent to ``run`` frame received."""
    exec_ms: float | None
    """``run`` frame to ``exit`` frame."""
    wall_ms: float | None
    """Request sent to ``exit`` frame received: what the caller waited for an answer."""
    cycle_ms: float
    """Request sent to the end of the stream, which includes this run's reset."""


async def run_in_pool(pool: Pool, profile: Profile, stdin: str, is_test: tuple[bool, ...]) -> PoolRunRecord:
    """One attempt, with no retry. Raises what a refused run raises: nothing has run then."""
    collected = _Collector(profile, is_test)
    run: PoolRun | None = None
    exit_: RunExit | None = None
    done: PoolRunDone | None = None
    failure: PoolRunError | None = None
    run_at: float | None = None
    exit_at: float | None = None
    command, *args = profile.runner_command
    started = time.perf_counter()
    try:
        # Reading on to run_done is what holds this caller's slot until the member is
        # back, so the next run finds it free. A cancel leaves early, and only closing
        # the stream gives the member back at once.
        stream = pool.stream_run(command, args, stdin=stdin, timeout_seconds=profile.batch_timeout_seconds)
        async with contextlib.aclosing(aiter(stream)) as chunks:
            async for chunk in chunks:
                if chunk.kind == "run":
                    run, run_at = chunk.run, time.perf_counter()
                elif chunk.kind == "stdout":
                    collected.stdout(chunk.data)
                elif chunk.kind == "stderr":
                    collected.stderr(chunk.data)
                elif chunk.kind == "exit":
                    exit_, exit_at = chunk.exit, time.perf_counter()
                elif chunk.kind == "run_done":
                    done = chunk.done
    except PoolRunError as error:
        failure = error
        run = run or error.run
    ended = time.perf_counter()
    return PoolRunRecord(
        run,
        exit_,
        done,
        failure,
        collected.finish(exit_ is not None, exit_.reason if exit_ else None),
        None if run_at is None else (run_at - started) * 1000,
        None if run_at is None or exit_at is None else (exit_at - run_at) * 1000,
        None if exit_at is None else (exit_at - started) * 1000,
        (ended - started) * 1000,
    )


async def pool_result(
    pool: Pool, profile: Profile, program: str, is_test: tuple[bool, ...], correlation_id: str, record: PoolRunRecord
) -> BatchResult:
    """Judge what a run's stream said. Raises when it says nothing about the program."""
    if record.run is None or record.startup_ms is None:
        raise SandboxInfrastructureError(f"{correlation_id}: pool run had no run frame: {record.failure}")
    if record.exit is None:
        oom_kills, pids_limit_hits = await _audited_kills(pool, record)
        if not oom_kills and not pids_limit_hits:
            raise SandboxInfrastructureError(
                f"{record.run.sandbox_id}: pool run ended without an exit record: {record.failure}"
            ) from record.failure
    else:
        usage = record.exit.usage
        oom_kills = usage.oom_kills if usage else None
        pids_limit_hits = usage.pids_limit_hits if usage else None
    run_status = _run_status(record.output, oom_kills, pids_limit_hits)
    usage = record.exit.usage if record.exit else None
    # Before Linux 6.12 the peak can't be reset, so on a reused member it may be an earlier run's.
    window_peak = usage.memory_peak_bytes if usage and usage.memory_peak_scope == "PEAK_SCOPE_WINDOW" else None
    return _batch_result(
        profile,
        program,
        is_test,
        correlation_id,
        run_status,
        record.output,
        sandbox_id=record.run.sandbox_id,
        startup_ms=round(record.startup_ms),
        exec_ms=round(record.exec_ms if record.exec_ms is not None else record.cycle_ms - record.startup_ms),
        peak_mem_bytes=window_peak,
        cpu_ms=usage.cpu_millis if usage else None,
        warm_start=record.run.warm,
        reset_ms=record.done.reset_ms if record.done else None,
        audit_log_id=record.exit.execution_id if record.exit else record.run.execution_id,
        prepared_reset_ms=record.run.reset_ms,
        reset_outcome=record.done.outcome if record.done else None,
        sandbox_run=record.run.sandbox_run,
    )


async def _audited_kills(pool: Pool, record: PoolRunRecord) -> tuple[int | None, int | None]:
    """A kill often takes the stream down with no exit, and only the audit trail then says why."""
    assert record.run is not None
    if record.run.sandbox_id is None:
        return None, None
    try:
        execs = await pool.execs(record.run.sandbox_id)
    except VoraError as error:
        log.warning("%s: reading the audit trail failed: %s", record.run.sandbox_id, error)
        return None, None
    for audited in execs:
        if audited.execution_id == record.run.execution_id:
            return audited.oom_kills, audited.pids_limit_hits
    return None, None


def batch_request(profile: Profile, program: str, task: Task) -> tuple[str, tuple[bool, ...]]:
    """The runner's stdin. Inputs are the train inputs (index 0..n-1), then the test inputs."""
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
    return stdin, is_test


async def _retrying(correlation_id: str, attempt: Callable[[], Awaitable[T]]) -> T:
    delays = iter(RETRY_DELAYS_S)
    while True:
        try:
            return await attempt()
        except (VoraError, httpx.TransportError) as error:
            delay = next(delays, None)
            if delay is None or not _is_retryable(error):
                raise
            if isinstance(error, RateLimitedError | UnavailableError) and error.retry_after is not None:
                delay = max(delay, error.retry_after)
            log.warning("%s: %s, retrying in %ss: %s", correlation_id, type(error).__name__, delay, error)
            await asyncio.sleep(delay)


def _batch_result(
    profile: Profile,
    program: str,
    is_test: tuple[bool, ...],
    correlation_id: str,
    run_status: RunStatus,
    output: _Exec,
    *,
    sandbox_id: str | None,
    startup_ms: int,
    exec_ms: int,
    peak_mem_bytes: int | None,
    cpu_ms: int | None,
    warm_start: bool = False,
    reset_ms: int | None = None,
    audit_log_id: str | None = None,
    prepared_reset_ms: int | None = None,
    reset_outcome: str | None = None,
    sandbox_run: int | None = None,
) -> BatchResult:
    unreported = _UNREPORTED_INPUT_STATUS[run_status]
    results = tuple(
        output.results.get(index)
        or GridResult(index, test, unreported, None, f"no result: the run ended {run_status}", 0)
        for index, test in enumerate(is_test)
    )
    done = output.done
    stderr_tail = done.stderr_tail if done is not None else output.stderr.decode("utf-8", "replace")
    return BatchResult(
        correlation_id=correlation_id,
        program_sha256=hashlib.sha256(program.encode("utf-8")).hexdigest(),
        run_status=run_status,
        grids=results,
        sandbox_id=sandbox_id,
        startup_ms=startup_ms,
        exec_ms=exec_ms,
        peak_mem_bytes=peak_mem_bytes,
        cpu_ms=cpu_ms,
        stderr_tail=_tail(stderr_tail, profile.output_tail_bytes),
        warm_start=warm_start,
        reset_ms=reset_ms,
        audit_log_id=audit_log_id,
        prepared_reset_ms=prepared_reset_ms,
        reset_outcome=reset_outcome,
        sandbox_run=sandbox_run,
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
    execution_id: str | None = None


@dataclass(frozen=True)
class _Run:
    sandbox_id: str
    startup_ms: int
    exec_ms: int
    exec: _Exec
    stats: Stats


async def _run_once(vora: Vora, profile: Profile, stdin: str, is_test: tuple[bool, ...]) -> _Run:
    started = time.monotonic()
    sandbox = await _create(vora, profile)
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


async def _create(vora: Vora, profile: Profile) -> Sandbox:
    creating = asyncio.ensure_future(
        vora.sandboxes.create(
            image=profile.image,
            backend=profile.backend,
            network=profile.network,
            cpu=f"{profile.cpu_millis}m",
            memory=profile.memory_bytes,
            pids=profile.pids,
            ttl=profile.ttl_seconds,
        )
    )
    try:
        return await asyncio.shield(creating)
    except asyncio.CancelledError:
        # The server may already be building it, and only the response names what to destroy.
        with contextlib.suppress(VoraError, httpx.HTTPError):
            await _destroy(await creating, profile)
        raise


class _Collector:
    """Parses a run's output as it streams. Shared by both ways of running a program."""

    def __init__(self, profile: Profile, is_test: tuple[bool, ...]) -> None:
        self._tail_bytes = profile.output_tail_bytes
        self._is_test = is_test
        self._lines = _LineBuffer()
        self._results: dict[int, GridResult] = {}
        self._done: _Done | None = None
        self._stderr = bytearray()

    def stdout(self, data: bytes) -> None:
        for line in self._lines.feed(data):
            parsed = _parse_line(line, self._is_test)
            if isinstance(parsed, _Done):
                self._done = self._done or parsed
            elif parsed is not None:
                self._results.setdefault(parsed.index, parsed)

    def stderr(self, data: bytes) -> None:
        self._stderr += data
        del self._stderr[: -self._tail_bytes]

    def finish(self, exited: bool, exit_reason: str | None, execution_id: str | None = None) -> _Exec:
        return _Exec(self._results, self._done, exited, exit_reason, bytes(self._stderr), execution_id)


async def _exec(sandbox: Sandbox, profile: Profile, stdin: str, is_test: tuple[bool, ...]) -> _Exec:
    collected = _Collector(profile, is_test)
    exited = False
    exit_reason: str | None = None
    execution_id: str | None = None
    started_streaming = False
    command, *args = profile.runner_command
    try:
        async for chunk in sandbox.stream_exec(
            command, args, stdin=stdin, timeout_seconds=profile.batch_timeout_seconds
        ):
            started_streaming = True
            if chunk.kind == "stdout":
                collected.stdout(chunk.data)
            elif chunk.kind == "stderr":
                collected.stderr(chunk.data)
            else:
                exited, exit_reason, execution_id = True, chunk.reason, chunk.execution_id
    except (VoraError, httpx.TransportError) as error:
        # Once output arrived the program has run; running it again would retry a program.
        if started_streaming and _is_transport_error(error):
            raise SandboxInfrastructureError(f"{sandbox.id}: exec stream broke: {error}") from error
        raise
    return collected.finish(exited, exit_reason, execution_id)


def _run_status(output: _Exec, oom_kills: int | None, pids_limit_hits: int | None) -> RunStatus:
    # Vora's exit reason can say EXITED after a pids-limit hit the runner survived, and
    # an OOM often takes the exec stream down with no exit record at all, so the
    # cgroup's counters come first.
    if oom_kills:
        reason: str | None = "OOM_KILLED"
    elif pids_limit_hits:
        reason = "PIDS_LIMIT_EXCEEDED"
    elif output.exited:
        reason = output.exit_reason
    else:
        raise SandboxInfrastructureError(
            f"exec stream ended without an exit record and no resource kill; stderr: {_stderr(output)}"
        )
    status = _RUN_STATUS_BY_EXIT_REASON.get(reason or "")
    if status is None:
        raise SandboxInfrastructureError(f"unexpected exit reason {reason!r}; stderr: {_stderr(output)}")
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
            line = self._pending + part
            if not self._skipping and len(line) <= MAX_LINE_BYTES:
                lines.append(bytes(line))
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


def _is_retryable(error: Exception) -> bool:
    # A 429 means nothing ran. A 503 usually means the same, but a runner lost just after
    # the program started also answers 503. A repeat is safe either way, because an ARC
    # program is a pure function of its input and only its result is kept. This loop is
    # the only retry on a run: nothing here passes the SDK's retry= as well. A 504, a
    # ConflictError such as PoolNotLoadedError and a PoolRunError are never repeated.
    return _is_transport_error(error) or isinstance(error, RateLimitedError | UnavailableError)


async def _destroy(sandbox: Sandbox, profile: Profile) -> None:
    try:
        await sandbox.destroy()
    except (VoraError, httpx.HTTPError):
        log.warning("destroy %s failed; its %ss TTL removes it", sandbox.id, profile.ttl_seconds, exc_info=True)


def _stderr(output: _Exec) -> str:
    return output.stderr.decode("utf-8", "replace")[-500:]


def _tail(text: str, limit: int) -> str:
    return text.encode("utf-8")[-limit:].decode("utf-8", "ignore")


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
