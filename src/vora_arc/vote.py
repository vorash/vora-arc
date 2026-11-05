"""Choose a task's answers from its passed candidates. Pure: no I/O."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .model import Grid, GridResult, GridStatus, Task
from .tasks import grid_problem

ATTEMPTS = 2


@dataclass(frozen=True)
class Ballot:
    """One passed candidate's outputs, one grid per test input, in input order."""

    outputs: tuple[Grid, ...]
    program_length: int


@dataclass(frozen=True)
class Answer:
    rank: int
    outputs: tuple[Grid, ...]
    votes: int
    correct: bool | None
    """None when the task doesn't reveal its test outputs."""


def ballot(program: str, grids: Iterable[GridResult]) -> Ballot | None:
    """A passed candidate's ballot, or None when a test output can't be an answer.

    A candidate passes on its train pairs alone, so its test outputs may still be
    errors. The program can also forge results, so an OK status proves nothing.
    """
    outputs: list[Grid] = []
    for grid in sorted((g for g in grids if g.is_test), key=lambda g: g.index):
        if grid.status is not GridStatus.OK or grid.output is None or grid_problem(grid.output) is not None:
            return None
        outputs.append(grid.output)
    return Ballot(tuple(outputs), len(program)) if outputs else None


def vote(task: Task, ballots: Iterable[Ballot]) -> tuple[Answer, ...]:
    """The top two distinct answers: most votes first, then the shortest program.

    A task with several test inputs is answered as a whole, so an answer is correct
    only if every grid in it is.
    """
    groups: dict[tuple[Grid, ...], list[int]] = {}
    for item in ballots:
        groups.setdefault(item.outputs, []).append(item.program_length)
    # The outputs break a remaining tie only so that a rerun gives the same answers.
    ranked = sorted(groups.items(), key=lambda group: (-len(group[1]), min(group[1]), group[0]))
    expected = tuple(case.output for case in task.test)
    return tuple(
        Answer(rank, outputs, len(lengths), None if None in expected else outputs == expected)
        for rank, (outputs, lengths) in enumerate(ranked[:ATTEMPTS], start=1)
    )
