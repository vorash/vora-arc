"""A report states only what a run logged. The rows are written by hand here, so every
expected number can be checked against them."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vora_arc import model
from vora_arc.model import Grid, GridResult, GridStatus, Pair, Task, Verdict
from vora_arc.report import (
    INFRA_ERROR,
    NOT_MEASURED,
    accuracy,
    accuracy_by_count,
    cost,
    gpu_price_from_env,
    render_markdown,
    time_split,
    verdict_counts,
    write_report,
)
from vora_arc.store import (
    AnswerRow,
    CandidateRow,
    PhaseRow,
    RunData,
    RunRow,
    RunSettings,
    SolveRun,
)

RIGHT: Grid = ((1,),)
WRONG: Grid = ((2,),)
TASK_A = Task(id="a", train=(Pair(((0,),), ((0,),)),), test=(model.TestCase(((9,),), RIGHT),))
TASK_B = Task(id="b", train=(Pair(((0,),), ((0,),)),), test=(model.TestCase(((9,),), RIGHT),))
STARTED = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
SETTINGS = RunSettings("arc1", "evaluation", 2, 32, True, "some-model", "python-arc", "gvisor", 8)


def candidate(
    task: str,
    index: int,
    verdict: Verdict | None = Verdict.PASSED,
    output: Grid = RIGHT,
    *,
    round_number: int = 1,
    program: str = "p",
) -> CandidateRow:
    grids = (GridResult(1, True, GridStatus.OK, output, None, 1),) if verdict is Verdict.PASSED else ()
    error = "VoraError: down" if verdict is None else None
    return CandidateRow(task, round_number, index, program, False, verdict, error, grids)


def phase(task: str, generation_ms: int | None = 1000, fresh: int = 32, cached: int = 0, round_number: int = 1) -> PhaseRow:
    return PhaseRow(task, round_number, generation_ms, fresh, cached, 40, 2.5)


def run_data(**changes: object) -> RunData:
    base = RunData(
        run=SolveRun("r1", SETTINGS, "finished", None, STARTED, STARTED + timedelta(seconds=90)),
        tasks={"arc1/a": TASK_A, "arc1/b": TASK_B},
        candidates=(
            candidate("arc1/a", 0),
            candidate("arc1/b", 0, Verdict.FAILED),
            candidate("arc1/b", 20, Verdict.PASSED),
            candidate("arc1/b", 21, Verdict.UNPARSEABLE, program=""),
        ),
        runs=(RunRow(100, 50, False, None), RunRow(120, 60, False, None)),
        phases=(phase("arc1/a"), phase("arc1/b"), phase("arc1/b", 500, 16, 0, round_number=2)),
        answers=(AnswerRow("arc1/a", 1, 1, 5, True), AnswerRow("arc1/b", 2, 1, 1, True)),
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def test_accuracy_counts_a_task_once_and_splits_by_round() -> None:
    rows = accuracy(run_data())
    assert [(r.solved, r.total) for r in rows] == [(2, 2), (1, 2), (1, 1)]
    assert rows[0].value == "2 / 2 (100.0%)"


def test_second_attempt_counts_but_a_wrong_answer_does_not() -> None:
    answers = (
        AnswerRow("arc1/a", 1, 1, 5, False),
        AnswerRow("arc1/a", 1, 2, 3, True),
        AnswerRow("arc1/b", 1, 1, 9, False),
    )
    assert accuracy(run_data(answers=answers))[0].value == "1 / 2 (50.0%)"


def test_round_two_is_not_measured_when_it_did_not_run() -> None:
    settings = replace(SETTINGS, refine=False)
    data = run_data(
        run=SolveRun("r1", settings, "finished", None, STARTED, STARTED),
        phases=(phase("arc1/a"), phase("arc1/b")),
        answers=(),
    )
    row = accuracy(data)[2]
    assert row.value == f"{NOT_MEASURED} (run without --refine)"
    assert accuracy(data)[0].value == "0 / 2 (0.0%)", "a measured zero stays a zero"


def test_tasks_with_hidden_outputs_are_left_out_of_accuracy() -> None:
    hidden = Task(id="a", train=TASK_A.train, test=(model.TestCase(((9,),), None),))
    data = run_data(tasks={"arc1/a": hidden}, answers=(AnswerRow("arc1/a", 1, 1, 5, None),), phases=(phase("arc1/a"),))
    assert accuracy(data)[0].value.startswith(NOT_MEASURED)
    assert all(point.solved is None for point in accuracy_by_count(data))


def test_count_above_the_samples_taken_is_not_measured() -> None:
    points = accuracy_by_count(run_data())
    assert [(p.count, p.solved) for p in points] == [(16, 1), (32, 2), (64, None), (128, None)]


def test_accuracy_by_count_revotes_on_each_prefix() -> None:
    candidates = (
        candidate("arc1/a", 0, output=WRONG),
        candidate("arc1/a", 1, output=WRONG),
        candidate("arc1/a", 2, output=((3,),)),
        candidate("arc1/a", 20, output=RIGHT),
        candidate("arc1/a", 21, output=RIGHT),
        candidate("arc1/a", 22, output=RIGHT),
    )
    data = run_data(tasks={"arc1/a": TASK_A}, candidates=candidates, phases=(phase("arc1/a"),))
    points = {p.count: p.solved for p in accuracy_by_count(data)}
    assert points[16] == 0, "the first 16 samples never produced the right output"
    assert points[32] == 1, "the later samples outvote the wrong outputs"


def test_accuracy_by_count_excludes_refinement() -> None:
    candidates = (candidate("arc1/a", 0, Verdict.FAILED), candidate("arc1/a", 0, round_number=2))
    data = run_data(tasks={"arc1/a": TASK_A}, candidates=candidates, phases=(phase("arc1/a"),))
    assert accuracy_by_count(data)[0].solved == 0


def test_verdict_counts_include_duplicates_and_name_vora_failures() -> None:
    candidates = (candidate("arc1/a", 0), candidate("arc1/a", 1), candidate("arc1/a", 2, None))
    counts = verdict_counts(run_data(candidates=candidates))
    assert counts[Verdict.PASSED.value] == 2
    assert counts[INFRA_ERROR] == 1
    assert counts[Verdict.TIMEOUT.value] == 0


def test_time_split_sums_what_was_logged() -> None:
    split = {p.name: p.seconds for p in time_split(run_data())}
    assert split["generation"] == pytest.approx(2.5)
    assert split["scheduling"] == pytest.approx(0.12)
    assert split["startup"] == pytest.approx(0.22)
    assert split["execution"] == pytest.approx(0.11)
    assert split["verification"] == pytest.approx(0.0075)
    assert split["reset"] is None


def test_a_cached_run_reports_no_generation_rather_than_zero() -> None:
    data = run_data(phases=(phase("arc1/a", None, 0, 32), phase("arc1/b", None, 0, 32)))
    generation = time_split(data)[0]
    assert generation.seconds is None
    assert "all 64 completions came from the cache" in generation.note
    run_cost = cost(data, 2.0)
    assert run_cost.gpu_hours is None and run_cost.eur_per_task is None
    text = render_markdown(data, 2.0, {})
    assert f"Cost per task: {NOT_MEASURED}" in text
    assert "0.000000" not in text


def test_cost_is_gpu_hours_times_price_per_task() -> None:
    data = run_data(phases=(phase("arc1/a", 1_800_000), phase("arc1/b", 1_800_000)))
    run_cost = cost(data, 2.0)
    assert run_cost.gpu_hours == pytest.approx(1.0)
    assert run_cost.eur_per_task == pytest.approx(1.0), "1 h at 2 EUR over 2 tasks"


def test_no_price_means_no_cost() -> None:
    run_cost = cost(run_data(), None)
    assert run_cost.eur_per_task is None and run_cost.gpu_hours is not None
    assert "GPU_EUR_PER_HOUR" in run_cost.note
    assert f"Price: {NOT_MEASURED}" in render_markdown(run_data(), None, {})


def test_a_partly_cached_run_says_what_its_cost_covers() -> None:
    data = run_data(phases=(phase("arc1/a", 1000, 8, 24),))
    assert "covers 8 of 32" in cost(data, 2.0).note
    assert "covers 8 of 32" in time_split(data)[0].note


def test_a_run_that_did_not_finish_says_so() -> None:
    failed = SolveRun("r1", SETTINGS, "failed", "ModelError: down", STARTED, None)
    text = render_markdown(run_data(run=failed), None, {})
    assert "did not finish" in text
    assert "ModelError: down" in text
    assert f"Total wall-clock: {NOT_MEASURED}" in text


def test_an_interrupted_run_and_a_live_run_read_differently() -> None:
    interrupted = render_markdown(run_data(run=SolveRun("r1", SETTINGS, "interrupted", None, STARTED, STARTED)), None, {})
    assert "- Status: interrupted\n" in interrupted
    assert "was interrupted, so it did not finish" in interrupted

    live = render_markdown(run_data(run=SolveRun("r1", SETTINGS, "running", None, STARTED, None)), None, {})
    assert "- Status: running\n" in live
    assert "It is still running, or its process was killed" in live
    assert "was interrupted" not in live
    assert f"Total wall-clock: {NOT_MEASURED}" in live


def test_an_error_page_cannot_break_the_report() -> None:
    page = "<html>\n# Bad Gateway\n\n[click](http://user:secret@gpu/v1) | `code` *x*\n</html>\n" + "x" * 2000
    failed = SolveRun("r1", SETTINGS, "failed", f"ModelError: {page}", STARTED, None)
    text = render_markdown(run_data(run=failed), None, {})
    status = next(line for line in text.splitlines() if line.startswith("- Status: failed"))
    assert "<" not in status and "&lt;html&gt;" in status, "a tag must not reach the Markdown"
    assert "\\[click\\](http://gpu/v1) \\| \\`code\\` \\*x\\*" in status, "nor a link, table cell, code span or emphasis"
    assert "# Bad Gateway" in status and "\n# Bad Gateway" not in text, "a heading in the page stays on the status line"
    assert "secret" not in text
    assert len(status) < 1000 and status.endswith("..."), "a long page is cut, and says so"
    assert text.index("- Total wall-clock") > text.index("- Status"), "the header carries on after the error"


def test_an_empty_run_invents_nothing(tmp_path: Path) -> None:
    empty = SolveRun("r1", SETTINGS, "failed", "ModelError: down", STARTED, None)
    data = run_data(run=empty, tasks={}, candidates=(), runs=(), phases=(), answers=())
    path = write_report(data, tmp_path, 2.0)
    text = path.read_text()
    assert list(tmp_path.glob("*.png")) == [], "no data, no chart"
    for phase_row in time_split(data):
        assert phase_row.seconds is None
    assert " 0 / " not in text
    assert "0.000" not in text
    assert "0.0%" not in text


def test_write_report_writes_markdown_and_charts(tmp_path: Path) -> None:
    path = write_report(run_data(), tmp_path / "r1", 2.0)
    text = path.read_text()
    assert path == tmp_path / "r1" / "report.md"
    for chart in ("accuracy_vs_candidates.png", "verdicts.png"):
        assert (tmp_path / "r1" / chart).read_bytes().startswith(b"\x89PNG")
        assert f"({chart})" in text


def test_the_price_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GPU_EUR_PER_HOUR", raising=False)
    assert gpu_price_from_env() is None
    monkeypatch.setenv("GPU_EUR_PER_HOUR", "1.5")
    assert gpu_price_from_env() == 1.5
    for bad in ("free", "0", "-1", "nan"):
        monkeypatch.setenv("GPU_EUR_PER_HOUR", bad)
        with pytest.raises(SystemExit, match="GPU_EUR_PER_HOUR"):
            gpu_price_from_env()
