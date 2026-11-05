"""Build the second-round prompt from a task's closest failures. Pure: no I/O."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .generate import ask_for_program, render_grid, task_prompt
from .model import BatchResult, Grid, Task

FAILURES_SHOWN = 3


@dataclass(frozen=True)
class Failure:
    """A distinct program that ran cleanly and got a train pair wrong."""

    program: str
    cell_accuracy: float
    result: BatchResult


def closest_failures(failures: Iterable[Failure]) -> list[Failure]:
    """The highest cell accuracies; the shorter program wins a tie."""
    return sorted(failures, key=lambda f: (-f.cell_accuracy, len(f.program)))[:FAILURES_SHOWN]


def pair_diff(expected: Grid, got: Grid) -> str:
    """Expected and got as rows of digits, with each wrong cell in square brackets."""
    if len(expected) != len(got) or len(expected[0]) != len(got[0]):
        return (
            f"expected a {_shape(expected)} grid:\n{render_grid(expected)}\n"
            f"got a {_shape(got)} grid:\n{render_grid(got)}"
        )
    marked = "\n".join(
        " ".join(str(g) if e == g else f"[{g}]" for e, g in zip(expected_row, got_row))
        for expected_row, got_row in zip(expected, got)
    )
    return f"expected:\n{render_grid(expected)}\ngot (wrong cells in brackets):\n{marked}"


def refine_prompt(task: Task, failures: Sequence[Failure]) -> str:
    parts = [task_prompt(task), "These programs were tried. Each gets at least one example wrong."]
    for number, failure in enumerate(failures, start=1):
        parts.append(
            f"Program {number} (cell accuracy {failure.cell_accuracy:.3f}):\n```python\n{failure.program}```"
        )
        got = {g.index: g.output for g in failure.result.grids if not g.is_test}
        for index, pair in enumerate(task.train):
            output = got[index]
            assert output is not None, "a failed verdict means every train output was a grid"
            verdict = "correct" if output == pair.output else pair_diff(pair.output, output)
            parts.append(f"Program {number}, example {index + 1}: {verdict}")
    return ask_for_program("\n\n".join(parts) + "\n\nCorrect the mistakes.")


def _shape(grid: Grid) -> str:
    return f"{len(grid)}x{len(grid[0])}"
