"""Turn one candidate's raw batch result into a verdict. Pure: no I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, overload

from vora_arc.model import BatchResult, Grid, GridResult, GridStatus, RunStatus, Task, Verdict
from vora_arc.tasks import grid_problem


@dataclass(frozen=True)
class Failed:
    """Ran cleanly but got a train pair wrong; carries how close it came."""

    cell_accuracy: float

    @property
    def verdict(self) -> Literal[Verdict.FAILED]:
        return Verdict.FAILED


@dataclass(frozen=True)
class Judged:
    """Any verdict other than `failed`, which has no accuracy to report."""

    verdict: Literal[
        Verdict.UNPARSEABLE,
        Verdict.TIMEOUT,
        Verdict.CRASHED,
        Verdict.INVALID,
        Verdict.MEMORIZED,
        Verdict.NONDETERMINISTIC,
        Verdict.PASSED,
    ]


Outcome = Failed | Judged


@overload
def verify(task: Task, program: None, result: None = None) -> Judged: ...
@overload
def verify(task: Task, program: str, result: BatchResult) -> Outcome: ...
def verify(task: Task, program: str | None, result: BatchResult | None = None) -> Outcome:
    """Judge one run of a candidate against the task's train pairs.

    `program` is None when no transform was extracted, and then there is no
    run to pass. A `passed` outcome has not been checked for determinism yet;
    see `check_determinism`.
    """
    if program is None:
        return Judged(Verdict.UNPARSEABLE)
    if result is None:
        raise ValueError("a parsed program needs a batch result to judge")

    if result.run_status is RunStatus.KILLED_TIMEOUT:
        return Judged(Verdict.TIMEOUT)
    if result.run_status is not RunStatus.COMPLETED:
        return Judged(Verdict.CRASHED)

    train = _train_results(task, result)
    statuses = {g.status for g in train}
    if GridStatus.TIMEOUT in statuses:
        return Judged(Verdict.TIMEOUT)
    if GridStatus.ERROR in statuses:
        return Judged(Verdict.CRASHED)

    outputs: list[Grid] = []
    for g in train:
        # The program runs in the worker that reports its results and can
        # forge them, so an OK status alone does not prove a valid grid.
        if g.status is not GridStatus.OK or g.output is None or grid_problem(g.output) is not None:
            return Judged(Verdict.INVALID)
        outputs.append(g.output)

    expected = [pair.output for pair in task.train]
    if outputs != expected:
        return Failed(cell_accuracy(expected, outputs))
    if _memorized(program, expected):
        return Judged(Verdict.MEMORIZED)
    return Judged(Verdict.PASSED)


def check_determinism(first: BatchResult, second: BatchResult) -> Judged:
    """Compare a survivor's run with a second run of the same program.

    Every input counts, test inputs included, because the test outputs are
    what gets voted on. Only status and output are compared; timings and
    error text may differ between runs.
    """

    def outcomes(result: BatchResult) -> dict[tuple[bool, int], tuple[GridStatus, Grid | None]]:
        return {(g.is_test, g.index): (g.status, g.output) for g in result.grids}

    if first.run_status is second.run_status and outcomes(first) == outcomes(second):
        return Judged(Verdict.PASSED)
    return Judged(Verdict.NONDETERMINISTIC)


def cell_accuracy(expected: list[Grid], got: list[Grid]) -> float:
    """Fraction of expected cells matched, over all pairs.

    A pair whose shape differs scores 0 correct cells but still counts its
    cells in the total, so a wrong-shaped answer pulls the score down.
    """
    total = sum(len(e) * len(e[0]) for e in expected)
    correct = 0
    for e, g in zip(expected, got, strict=True):
        if len(e) == len(g) and len(e[0]) == len(g[0]):
            correct += sum(a == b for er, gr in zip(e, g) for a, b in zip(er, gr))
    return correct / total


def _train_results(task: Task, result: BatchResult) -> list[GridResult]:
    by_index = {g.index: g for g in result.grids if not g.is_test}
    missing = [i for i in range(len(task.train)) if i not in by_index]
    if missing:
        raise ValueError(
            f"{result.correlation_id}: completed run has no result for train inputs {missing}"
        )
    return [by_index[i] for i in range(len(task.train))]


def _normalize(text: str) -> str:
    # One spelling for every list/tuple literal: no whitespace, brackets only,
    # no trailing commas. `((1, 2),\n (3, 4),)` and `[[1,2],[3,4]]` both
    # become `[[1,2],[3,4]]`.
    text = re.sub(r"\s+", "", text).translate(str.maketrans("()", "[]"))
    return text.replace(",]", "]")


def _memorized(program: str, outputs: list[Grid]) -> bool:
    source = _normalize(program)
    return any(_normalize(repr([list(row) for row in grid])) in source for grid in outputs)
