"""Canned programs and sandbox results for pipeline tests. Nothing here executes a program:
`CannedRuns` replaces `run_batch` and looks each program up in a table."""

from __future__ import annotations

from typing import Any

import pytest
from fake_model import fenced

from vora_arc import model, schedule
from vora_arc.model import (
    BatchResult,
    Grid,
    GridResult,
    GridStatus,
    Pair,
    RunStatus,
    Task,
)

TASK = Task(
    id="task0001",
    train=(Pair(((1, 2),), ((2, 1),)), Pair(((3, 4),), ((4, 3),))),
    test=(model.TestCase(((5, 6),), ((6, 5),)),),
)
RIGHT_TRAIN: tuple[Grid, ...] = (((2, 1),), ((4, 3),))
RIGHT_TEST: Grid = ((6, 5),)

GOOD = "def transform(grid):\n    return [row[::-1] for row in grid]\n"
GOOD_LONGER = "def transform(grid):\n    # same rule, more words\n    return [list(reversed(row)) for row in grid]\n"
WRONG_ANSWER_PASSES = "def transform(grid):\n    return [row[::-1] for row in grid]  # wrong on the test input\n"
WRONG = "def transform(grid):\n    return grid\n"
CLOSE = "def transform(grid):\n    return [[row[1], 0] for row in grid]\n"
CLOSER = "def transform(grid):\n    return [row[::-1] if row[0] == 1 else row for row in grid]\n"
CRASHES = "def transform(grid):\n    raise ValueError('no')\n"
HANGS = "def transform(grid):\n    while True:\n        pass\n"
FLAKY = "import random\ndef transform(grid):\n    return [row[::-1] for row in grid]  # plus noise\n"
MEMORIZED = "def transform(grid):\n    return {1: [[2, 1]], 3: [[4, 3]]}.get(grid[0][0], grid)\n"
JUNK = "I could not work out the rule."


def batch(
    train: tuple[Grid | None, ...] = RIGHT_TRAIN,
    test: Grid | None = RIGHT_TEST,
    *,
    train_status: GridStatus = GridStatus.OK,
    run_status: RunStatus = RunStatus.COMPLETED,
) -> BatchResult:
    grids = tuple(GridResult(i, False, train_status, g, None, 2) for i, g in enumerate(train)) + (
        GridResult(len(train), True, GridStatus.OK if test is not None else GridStatus.ERROR, test, None, 2),
    )
    return BatchResult("c", "s", run_status, grids, "sbx", 100, 50, 1 << 20, 30, "")


TABLE: dict[str, list[BatchResult]] = {
    GOOD: [batch()],
    GOOD_LONGER: [batch()],
    WRONG_ANSWER_PASSES: [batch(test=((9, 9),))],
    WRONG: [batch(train=(((1, 2),), ((3, 4),)))],
    CLOSE: [batch(train=(((2, 0),), ((4, 0),)))],
    CLOSER: [batch(train=(((2, 1),), ((3, 4),)))],
    CRASHES: [batch(train=(None, None), train_status=GridStatus.ERROR, test=None)],
    HANGS: [batch(train=(None, None), train_status=GridStatus.TIMEOUT, test=None, run_status=RunStatus.KILLED_TIMEOUT)],
    FLAKY: [batch(), batch(test=((0, 0),))],
    MEMORIZED: [batch()],
}


class CannedRuns:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.programs: list[str] = []
        monkeypatch.setattr(schedule, "run_batch", self)

    async def __call__(self, vora: Any, profile: Any, program: str, task: Task, *, correlation_id: str) -> BatchResult:
        attempt = self.programs.count(program)
        self.programs.append(program)
        results = TABLE[program]
        return results[min(attempt, len(results) - 1)]


def completions(*programs: str) -> list[str]:
    return [program if program == JUNK else fenced(program) for program in programs]
