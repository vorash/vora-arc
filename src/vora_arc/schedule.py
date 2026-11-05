"""Run a task's unique programs in sandboxes. `schedule` is the only entry point, so a
different backend (Ray, once a GPU host exists) replaces this module and nothing else."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from vora import Vora, VoraError

from .client import SandboxInfrastructureError, run_batch
from .model import BatchResult, Task, Verdict
from .profile import Profile
from .verify import Outcome, check_determinism, verify

log = logging.getLogger(__name__)

# The spec's default is the warm pool's size, 8. There is no pool yet, so it stands alone.
DEFAULT_MAX_CONCURRENCY = 8


@dataclass(frozen=True)
class Judgement:
    outcome: Outcome
    runs: tuple[BatchResult, ...]
    verify_ms: float


@dataclass(frozen=True)
class InfraFailure:
    """Vora failed, which says nothing about the program, so there is no verdict."""

    error: str


@dataclass(frozen=True)
class ProgramResult:
    program: str
    sha256: str
    queue_ms: int
    result: Judgement | InfraFailure


def program_sha256(program: str) -> str:
    return hashlib.sha256(program.encode("utf-8")).hexdigest()


def max_concurrency_from_env() -> int:
    raw = os.environ.get("VORA_MAX_CONCURRENCY")
    if raw is None:
        return DEFAULT_MAX_CONCURRENCY
    if not raw.isdecimal() or int(raw) < 1:
        raise SystemExit(f"VORA_MAX_CONCURRENCY must be a positive integer, got {raw!r}")
    return int(raw)


async def judge(vora: Vora, profile: Profile, task: Task, program: str, correlation_id: str) -> Judgement:
    """Run a program, judge it, and re-run a survivor to prove it deterministic."""
    first = await run_batch(vora, profile, program, task, correlation_id=correlation_id)
    started = time.perf_counter()
    outcome = verify(task, program, first)
    verify_ms = _since_ms(started)
    if outcome.verdict is not Verdict.PASSED:
        return Judgement(outcome, (first,), verify_ms)
    second = await run_batch(vora, profile, program, task, correlation_id=f"{correlation_id}/rerun")
    started = time.perf_counter()
    outcome = check_determinism(first, second)
    return Judgement(outcome, (first, second), verify_ms + _since_ms(started))


async def schedule(
    vora: Vora,
    profile: Profile,
    task: Task,
    programs: Sequence[str],
    *,
    max_concurrency: int,
) -> dict[str, ProgramResult]:
    """Judge each distinct program once, at most `max_concurrency` at a time, keyed by SHA-256.

    One program's Vora failure is reported in its result and doesn't stop the others.
    Any other exception is a bug: it cancels the other jobs, and their sandboxes are
    destroyed before it reaches the caller, who may close the client next.
    """
    gate = asyncio.Semaphore(max_concurrency)

    async def job(sha256: str, program: str) -> ProgramResult:
        queued = time.perf_counter()
        async with gate:
            queue_ms = round(_since_ms(queued))
            result: Judgement | InfraFailure
            try:
                result = await judge(vora, profile, task, program, f"{task.id}/{sha256[:12]}")
            except (SandboxInfrastructureError, VoraError, httpx.HTTPError) as error:
                log.warning("%s/%s: Vora failed: %s", task.id, sha256[:12], error)
                result = InfraFailure(f"{type(error).__name__}: {error}")
        return ProgramResult(program, sha256, queue_ms, result)

    unique = {program_sha256(program): program for program in programs}
    try:
        async with asyncio.TaskGroup() as group:
            jobs = [group.create_task(job(sha256, program)) for sha256, program in unique.items()]
    except ExceptionGroup as failures:
        raise failures.exceptions[0] from failures
    return {result.sha256: result for result in (done.result() for done in jobs)}


def _since_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
