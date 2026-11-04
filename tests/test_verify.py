from dataclasses import replace

import pytest

from vora_arc import model
from vora_arc.model import BatchResult, Grid, GridResult, GridStatus, Pair, RunStatus, Task, Verdict
from vora_arc.verify import Failed, Judged, check_determinism, verify

# Rotate 180 degrees. Two train pairs of different sizes and one test input.
TASK = Task(
    id="rot180",
    train=(
        Pair(input=((1, 2), (3, 4)), output=((4, 3), (2, 1))),
        Pair(input=((5, 0, 0),), output=((0, 0, 5),)),
    ),
    test=(model.TestCase(input=((7, 8),), output=((8, 7),)),),
)
GOOD = "def transform(grid):\n    return [row[::-1] for row in grid[::-1]]\n"
WRONG = "def transform(grid):\n    return grid\n"


def ok(index: int, output: Grid, is_test: bool = False) -> GridResult:
    return GridResult(index=index, is_test=is_test, status=GridStatus.OK, output=output, error=None, wall_ms=1)


def bad(index: int, status: GridStatus) -> GridResult:
    return GridResult(index=index, is_test=False, status=status, output=None, error="boom", wall_ms=1)


def batch(*grids: GridResult, run_status: RunStatus = RunStatus.COMPLETED) -> BatchResult:
    return BatchResult(
        correlation_id="rot180/c1",
        program_sha256="0" * 64,
        run_status=run_status,
        grids=grids,
        sandbox_id="sb",
        startup_ms=1,
        exec_ms=1,
        peak_mem_bytes=None,
        cpu_ms=None,
        stderr_tail="",
    )


def correct(**changes: object) -> BatchResult:
    """A run where every input got the right answer."""
    result = batch(ok(0, ((4, 3), (2, 1))), ok(1, ((0, 0, 5),)), ok(0, ((8, 7),), is_test=True))
    return replace(result, **changes)  # type: ignore[arg-type]


def test_correct_program_passes() -> None:
    assert verify(TASK, GOOD, correct()) == Judged(Verdict.PASSED)


def test_no_extracted_program_is_unparseable() -> None:
    assert verify(TASK, None) == Judged(Verdict.UNPARSEABLE)


def test_parsed_program_without_a_run_is_an_error() -> None:
    # Not unparseable: the program exists, the caller just never ran it.
    with pytest.raises(ValueError, match="needs a batch result"):
        verify(TASK, GOOD, None)  # type: ignore[call-overload]


@pytest.mark.parametrize(
    ("run_status", "verdict"),
    [
        (RunStatus.KILLED_TIMEOUT, Verdict.TIMEOUT),
        (RunStatus.KILLED_OOM, Verdict.CRASHED),
        (RunStatus.POLICY_VIOLATION, Verdict.CRASHED),
    ],
)
def test_killed_run_is_rejected_even_when_train_outputs_are_right(
    run_status: RunStatus, verdict: Verdict
) -> None:
    # A batch killed by the sandbox is not a solution, however far it got.
    assert verify(TASK, GOOD, correct(run_status=run_status)).verdict is verdict


@pytest.mark.parametrize(
    ("statuses", "verdict"),
    [
        ((GridStatus.TIMEOUT, GridStatus.OK), Verdict.TIMEOUT),
        ((GridStatus.OK, GridStatus.ERROR), Verdict.CRASHED),
        # Any timed-out train input makes the verdict timeout, whatever else failed.
        ((GridStatus.ERROR, GridStatus.TIMEOUT), Verdict.TIMEOUT),
        ((GridStatus.OK, GridStatus.INVALID), Verdict.INVALID),
        # Crashes are checked before invalid outputs.
        ((GridStatus.INVALID, GridStatus.ERROR), Verdict.CRASHED),
    ],
)
def test_train_input_status_decides_verdict(statuses: tuple[GridStatus, GridStatus], verdict: Verdict) -> None:
    right = [((4, 3), (2, 1)), ((0, 0, 5),)]
    grids = [ok(i, right[i]) if s is GridStatus.OK else bad(i, s) for i, s in enumerate(statuses)]
    assert verify(TASK, GOOD, batch(*grids)).verdict is verdict


@pytest.mark.parametrize("output", [((4, 3), (2, 11)), ((4, 3), (2,)), ()])
def test_ok_status_with_malformed_grid_is_invalid(output: Grid) -> None:
    # The runner's OK is not trusted: the program can forge its result line.
    result = batch(ok(0, output), ok(1, ((0, 0, 5),)))
    assert verify(TASK, GOOD, result) == Judged(Verdict.INVALID)


def test_test_input_failures_do_not_change_verdict() -> None:
    # Only train pairs are checked; the test answer is unknown at solve time.
    result = batch(ok(0, ((4, 3), (2, 1))), ok(1, ((0, 0, 5),)), replace(bad(0, GridStatus.ERROR), is_test=True))
    assert verify(TASK, GOOD, result) == Judged(Verdict.PASSED)


def test_completed_run_missing_a_train_result_is_an_error() -> None:
    # A completed batch always reports every input; a gap is a client bug, not a verdict.
    with pytest.raises(ValueError, match=r"rot180/c1: .* train inputs \[1\]"):
        verify(TASK, GOOD, batch(ok(0, ((4, 3), (2, 1)))))


def test_wrong_output_fails_with_cell_accuracy() -> None:
    # Pair 0 gets 2 of 4 cells, pair 1 gets 1 of 3: 3 of 7 overall.
    result = batch(ok(0, ((4, 3), (0, 0))), ok(1, ((5, 0, 0),)))
    assert verify(TASK, WRONG, result) == Failed(cell_accuracy=3 / 7)


def test_wrong_shape_counts_zero_cells_but_keeps_its_weight() -> None:
    # Pair 0 has the wrong shape: 0 of its 4 cells, pair 1 is fully right: 3 of 7.
    result = batch(ok(0, ((4, 3, 2, 1),)), ok(1, ((0, 0, 5),)))
    assert verify(TASK, WRONG, result) == Failed(cell_accuracy=3 / 7)


def test_failed_outcome_reports_failed_verdict() -> None:
    assert Failed(cell_accuracy=0.5).verdict is Verdict.FAILED


@pytest.mark.parametrize(
    "literal",
    [
        "[[4, 3], [2, 1]]",
        "[[4,3],[2,1]]",
        "((4, 3), (2, 1))",
        "[\n    (4, 3),\n    (2, 1),\n]",
        "[[0, 0, 5]]",
        "((0, 0, 5),)",
        "'[[0,0,5]]'",
    ],
)
def test_correct_program_holding_a_train_output_literal_is_memorized(literal: str) -> None:
    program = f"ANSWER = {literal}\n" + GOOD
    assert verify(TASK, program, correct()) == Judged(Verdict.MEMORIZED)


def test_wrong_program_holding_a_literal_is_failed_not_memorized() -> None:
    # Failure is checked first, so the accuracy of a wrong answer is never lost.
    program = "def transform(grid):\n    return [[4, 3], [2, 1]]\n"
    result = batch(ok(0, ((4, 3), (2, 1))), ok(1, ((4, 3), (2, 1))))
    assert verify(TASK, program, result) == Failed(cell_accuracy=4 / 7)


def test_literal_of_a_train_input_is_not_memorization() -> None:
    program = "EXAMPLE = [[1, 2], [3, 4]]\n" + GOOD
    assert verify(TASK, program, correct()) == Judged(Verdict.PASSED)


def test_identical_reruns_are_deterministic() -> None:
    # Timings and error text vary between runs and must not count.
    second = replace(correct(), exec_ms=99, grids=tuple(replace(g, wall_ms=50) for g in correct().grids))
    assert check_determinism(correct(), second) == Judged(Verdict.PASSED)


def test_rerun_with_different_test_output_is_nondeterministic() -> None:
    # The test output is what gets voted on, so it must be stable too.
    second = batch(ok(0, ((4, 3), (2, 1))), ok(1, ((0, 0, 5),)), ok(0, ((7, 8),), is_test=True))
    assert check_determinism(correct(), second) == Judged(Verdict.NONDETERMINISTIC)


def test_rerun_with_different_status_is_nondeterministic() -> None:
    second = batch(ok(0, ((4, 3), (2, 1))), ok(1, ((0, 0, 5),)), replace(bad(0, GridStatus.TIMEOUT), is_test=True))
    assert check_determinism(correct(), second) == Judged(Verdict.NONDETERMINISTIC)


def test_rerun_killed_is_nondeterministic() -> None:
    second = correct(run_status=RunStatus.KILLED_TIMEOUT)
    assert check_determinism(correct(), second) == Judged(Verdict.NONDETERMINISTIC)
