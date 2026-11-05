"""Solve a task: sample programs, judge them, vote, and refine once if asked."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from .generate import Sampled, ask_for_program, extract_program, task_prompt
from .model import BatchResult, Task, Verdict
from .refine import Failure, closest_failures, refine_prompt
from .schedule import InfraFailure, ProgramResult, program_sha256
from .verify import Failed
from .vote import Answer, Ballot, ballot, vote

# Given a prompt and a sample count.
Sampler = Callable[[str, int], Awaitable[Sampled]]
# Given the task and its new programs. See schedule.schedule.
Scheduler = Callable[[Task, Sequence[str]], Awaitable[Mapping[str, ProgramResult]]]


@dataclass(frozen=True)
class CandidateResult:
    """One sampled completion. A duplicate has `first_copy` set and holds no runs of its own."""

    round: int
    sample_index: int
    prompt_hash: str
    program: str | None
    first_copy: tuple[int, int] | None
    """The (round, sample_index) of the candidate that ran this program."""
    verdict: Verdict | None
    """None only when Vora failed, and then `infra_error` says how."""
    cell_accuracy: float | None
    infra_error: str | None
    runs: tuple[BatchResult, ...]

    @property
    def program_sha256(self) -> str | None:
        return None if self.program is None else program_sha256(self.program)


@dataclass(frozen=True)
class RoundTiming:
    round: int
    generation_ms: int | None
    fresh_completions: int
    cached_completions: int
    scheduling_ms: int | None
    verification_ms: float | None
    """None when nothing was run or judged, so there is no time to report."""


@dataclass(frozen=True)
class TaskResult:
    task: Task
    candidates: tuple[CandidateResult, ...]
    answers: tuple[Answer, ...]
    answer_round: int
    timings: tuple[RoundTiming, ...]

    @property
    def infra_errors(self) -> int:
        return sum(candidate.infra_error is not None for candidate in self.candidates)

    @property
    def solved(self) -> bool:
        return any(answer.correct for answer in self.answers)


async def solve_task(
    task: Task,
    *,
    sampler: Sampler,
    scheduler: Scheduler,
    samples: int,
    refine: bool,
) -> TaskResult:
    seen: dict[str, CandidateResult] = {}
    candidates, timing = await _run_round(task, 1, ask_for_program(task_prompt(task)), samples, sampler, scheduler, seen)
    timings = [timing]
    if refine and not _passed(candidates):
        failures = closest_failures(_failures(candidates))
        if failures:
            more, timing = await _run_round(
                task, 2, refine_prompt(task, failures), max(1, samples // 2), sampler, scheduler, seen
            )
            candidates += more
            timings.append(timing)

    started = time.perf_counter()
    answers = vote(task, _ballots(candidates, seen))
    vote_ms = (time.perf_counter() - started) * 1000
    last = timings[-1]
    if last.verification_ms is not None:
        timings[-1] = replace(last, verification_ms=last.verification_ms + vote_ms)
    return TaskResult(task, tuple(candidates), answers, last.round, tuple(timings))


async def _run_round(
    task: Task,
    round_number: int,
    prompt: str,
    samples: int,
    sampler: Sampler,
    scheduler: Scheduler,
    seen: dict[str, CandidateResult],
) -> tuple[list[CandidateResult], RoundTiming]:
    sampled = await sampler(prompt, samples)
    programs = [extract_program(text) for text in sampled.texts]
    new = list(dict.fromkeys(p for p in programs if p is not None and program_sha256(p) not in seen))
    results = await scheduler(task, new) if new else {}

    candidates: list[CandidateResult] = []
    for index, program in enumerate(programs):
        candidate = _candidate(round_number, index, sampled.prompt_hash, program, results, seen)
        if candidate.program_sha256 is not None:
            seen.setdefault(candidate.program_sha256, candidate)
        candidates.append(candidate)

    judgements = [r.result for r in results.values() if not isinstance(r.result, InfraFailure)]
    timing = RoundTiming(
        round_number,
        sampled.request_ms,
        sampled.fresh,
        sampled.cached,
        sum(r.queue_ms for r in results.values()) if results else None,
        sum(j.verify_ms for j in judgements) if judgements else None,
    )
    return candidates, timing


def _candidate(
    round_number: int,
    index: int,
    prompt_hash: str,
    program: str | None,
    results: Mapping[str, ProgramResult],
    seen: Mapping[str, CandidateResult],
) -> CandidateResult:
    def make(
        first_copy: tuple[int, int] | None,
        verdict: Verdict | None,
        accuracy: float | None = None,
        error: str | None = None,
        runs: tuple[BatchResult, ...] = (),
    ) -> CandidateResult:
        return CandidateResult(round_number, index, prompt_hash, program, first_copy, verdict, accuracy, error, runs)

    if program is None:
        return make(None, Verdict.UNPARSEABLE)
    sha256 = program_sha256(program)
    if (first := seen.get(sha256)) is not None:
        return make((first.round, first.sample_index), first.verdict, first.cell_accuracy, first.infra_error)
    result = results[sha256].result
    if isinstance(result, InfraFailure):
        return make(None, None, error=result.error)
    accuracy = result.outcome.cell_accuracy if isinstance(result.outcome, Failed) else None
    return make(None, result.outcome.verdict, accuracy, runs=result.runs)


def _passed(candidates: Sequence[CandidateResult]) -> list[CandidateResult]:
    return [candidate for candidate in candidates if candidate.verdict is Verdict.PASSED]


def _failures(candidates: Sequence[CandidateResult]) -> list[Failure]:
    return [
        Failure(c.program, c.cell_accuracy, c.runs[0])
        for c in candidates
        if c.verdict is Verdict.FAILED and c.first_copy is None and c.program and c.cell_accuracy is not None
    ]


def _ballots(candidates: Sequence[CandidateResult], seen: Mapping[str, CandidateResult]) -> list[Ballot]:
    """One ballot per passed sample: a program the model wrote twice gets two votes."""
    ballots: list[Ballot] = []
    for candidate in _passed(candidates):
        assert candidate.program is not None and candidate.program_sha256 is not None
        item = ballot(candidate.program, seen[candidate.program_sha256].runs[0].grids)
        if item is not None:
            ballots.append(item)
    return ballots
