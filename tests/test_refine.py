"""What a second round is told about the closest failures."""

from __future__ import annotations

from vora_arc import model
from vora_arc.model import (
    BatchResult,
    Grid,
    GridResult,
    GridStatus,
    Pair,
    RunStatus,
    Task,
)
from vora_arc.refine import Failure, closest_failures, pair_diff, refine_prompt

TASK = Task(
    id="t",
    train=(Pair(((1, 2), (3, 4)), ((4, 3), (2, 1))), Pair(((5,),), ((5,),))),
    test=(model.TestCase(((7,),), ((7,),)),),
)


def result(*train_outputs: Grid) -> BatchResult:
    grids = tuple(GridResult(i, False, GridStatus.OK, g, None, 1) for i, g in enumerate(train_outputs))
    return BatchResult("c", "s", RunStatus.COMPLETED, grids, "sb", 1, 1, None, None, "")


def failure(program: str, accuracy: float) -> Failure:
    return Failure(program, accuracy, result(((4, 3), (2, 9)), ((5,),)))


def test_the_three_closest_failures_are_chosen() -> None:
    failures = [failure(f"p{a}", a) for a in (0.1, 0.9, 0.5, 0.7)]
    assert [f.cell_accuracy for f in closest_failures(failures)] == [0.9, 0.7, 0.5]


def test_a_tie_goes_to_the_shorter_program() -> None:
    chosen = closest_failures([failure("longer program", 0.5), failure("short", 0.5)])
    assert chosen[0].program == "short"


def test_the_diff_marks_exactly_the_wrong_cells() -> None:
    diff = pair_diff(((4, 3), (2, 1)), ((4, 3), (9, 1)))
    assert "expected:\n4 3\n2 1" in diff
    assert "4 3\n[9] 1" in diff


def test_a_wrong_shape_is_named_instead_of_marked() -> None:
    diff = pair_diff(((1, 2),), ((1,), (2,)))
    assert "expected a 1x2 grid" in diff
    assert "got a 2x1 grid" in diff
    assert "[" not in diff


def test_the_prompt_has_the_task_each_program_and_its_diffs() -> None:
    prompt = refine_prompt(TASK, [failure("def transform(g):\n    return 'first'\n", 0.75)])
    assert "Example 1 input:\n1 2\n3 4" in prompt
    assert "return 'first'" in prompt
    assert "cell accuracy 0.750" in prompt
    assert "Program 1, example 1: expected:" in prompt
    assert "[9]" in prompt
    assert "Program 1, example 2: correct" in prompt
    assert "def transform(grid: list[list[int]]) -> list[list[int]]" in prompt


def test_the_prompt_never_shows_a_test_output() -> None:
    task = Task(id="t", train=TASK.train, test=(model.TestCase(((7,),), ((6, 6, 6),)),))
    assert "6 6 6" not in refine_prompt(task, [failure("p", 0.5)])
