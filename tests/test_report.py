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


def test_a_task_vora_failed_on_is_shown_with_and_without_it() -> None:
    data = run_data(
        candidates=(candidate("arc1/a", 0), candidate("arc1/b", 0, None)),
        answers=(AnswerRow("arc1/a", 1, 1, 1, True),),
    )
    assert [row.value for row in accuracy(data)][:2] == ["1 / 2 (50.0%)", "1 / 2 (50.0%)"]
    assert [row.value for row in accuracy(data, leave_out={"arc1/b"})][:2] == ["1 / 1 (100.0%)", "1 / 1 (100.0%)"]
    text = render_markdown(data, None, {})
    assert "Vora failed on candidates in 1 of 2 tasks, and 1 of those had no program judged at all" in text
    assert "can't be judged" in text
    assert "| Solved, counting those tasks | Solved, leaving those tasks out |" in text
    assert "| Overall, 2 attempts | 1 / 2 (50.0%) | 1 / 1 (100.0%) |" in text


def test_an_outage_on_every_task_is_not_reported_as_a_score_of_zero_alone() -> None:
    data = run_data(candidates=(candidate("arc1/a", 0, None), candidate("arc1/b", 0, None)), answers=())
    text = render_markdown(data, None, {})
    assert "Vora failed on candidates in 2 of 2 tasks, and 2 of those had no program judged at all" in text
    assert f"| Overall, 2 attempts | 0 / 2 (0.0%) | {NOT_MEASURED} (no scored task is left) |" in text
    assert "Tasks Vora failed on are included here" in text, "the re-vote table counts them too"


def test_leaving_a_task_out_takes_it_out_of_both_sides_of_the_fraction() -> None:
    data = run_data(
        candidates=(candidate("arc1/a", 0), candidate("arc1/a", 1, None), candidate("arc1/b", 0, Verdict.FAILED)),
        answers=(AnswerRow("arc1/a", 1, 1, 1, True), AnswerRow("arc1/b", 1, 1, 1, False)),
    )
    text = render_markdown(data, None, {})
    assert "and 0 of those had no program judged at all" in text, "task a still had one program judged"
    assert "| Overall, 2 attempts | 1 / 2 (50.0%) | 0 / 1 (0.0%) |" in text, "a solved task can't stay on top of a smaller total"


def test_a_candidate_with_no_program_does_not_count_as_a_judged_program() -> None:
    unparseable = replace(candidate("arc1/a", 1, Verdict.UNPARSEABLE), program=None)
    data = run_data(candidates=(candidate("arc1/a", 0, None), unparseable))
    assert "and 1 of those had no program judged at all" in render_markdown(data, None, {})


def test_a_run_without_vora_failures_has_no_such_column() -> None:
    text = render_markdown(run_data(), None, {})
    assert "| Overall, 2 attempts | 2 / 2 (100.0%) |" in text
    assert "Vora failed" not in text and "leaving those tasks out" not in text


def test_time_split_sums_what_was_logged() -> None:
    split = {p.name: p.seconds for p in time_split(run_data())}
    assert split["generation"] == pytest.approx(2.5)
    assert split["scheduling"] == pytest.approx(0.12)
    assert split["startup"] == pytest.approx(0.22)
    assert split["execution"] == pytest.approx(0.11)
    assert split["verification"] == pytest.approx(0.0075)
    assert split["reset"] is None


def test_a_run_with_no_warm_start_says_every_sandbox_was_fresh() -> None:
    data = run_data(runs=(RunRow(100, 50, False, None), RunRow(120, 60, False, None)))
    reset = time_split(data)[-1]
    assert reset.seconds is None
    assert reset.note == "every run used a fresh sandbox"


def test_a_run_mixing_warm_and_cold_says_so_with_its_counts() -> None:
    data = run_data(runs=(RunRow(100, 50, False, None), RunRow(1, 60, True, 3), RunRow(1, 60, True, None)))
    reset = time_split(data)[-1]
    assert reset.seconds == pytest.approx(0.003), "only what was reported is summed"
    assert "the rest a fresh one" in reset.note and "every run" not in reset.note
    assert "2 of 3 runs used a pool's running sandbox" in reset.note
    assert "1 of 3 reported a reset" in reset.note


def test_a_report_never_shows_a_count_for_denied_syscalls_or_blocked_network() -> None:
    text = render_markdown(run_data(), None, {})
    assert f"- Denied syscalls: {NOT_MEASURED}." in text
    assert f"- Blocked network attempts: {NOT_MEASURED}." in text
    assert "floor" in text and "restricted" in text


def test_a_cached_run_reports_no_generation_rather_than_zero() -> None:
    data = run_data(phases=(phase("arc1/a", None, 0, 32), phase("arc1/b", None, 0, 32)))
    generation = time_split(data)[0]
    assert generation.seconds is None
    assert "all 64 completions came from the cache" in generation.note
    run_cost = cost(data, 2.0)
    for basis in (run_cost.wall_clock, run_cost.request_time):
        assert (basis.hours, basis.eur, basis.eur_per_task) == (None, None, None), "no request means no GPU time to bill"
    text = render_markdown(data, 2.0, {})
    assert f"Cost per task: {NOT_MEASURED}" in text
    assert "0.000000" not in text


def test_cost_leads_with_wall_clock_and_gives_the_request_time_as_the_lower_bound() -> None:
    data = run_data(
        run=SolveRun("r1", SETTINGS, "finished", None, STARTED, STARTED + timedelta(hours=2)),
        phases=(phase("arc1/a", 1_800_000), phase("arc1/b", 1_800_000)),
    )
    run_cost = cost(data, 2.0)
    assert run_cost.wall_clock.hours == pytest.approx(2.0)
    assert run_cost.wall_clock.eur == pytest.approx(4.0), "2 h rented at 2 EUR"
    assert run_cost.wall_clock.eur_per_task == pytest.approx(2.0), "over 2 tasks"
    assert run_cost.request_time.hours == pytest.approx(1.0)
    assert run_cost.request_time.eur == pytest.approx(2.0)
    assert run_cost.request_time.eur_per_task == pytest.approx(1.0)
    assert run_cost.notes == ()

    text = render_markdown(data, 2.0, {})
    assert "- Wall-clock, what a rented GPU costs for this run: 2.000000 GPU-hours, 4.000000 EUR\n" in text
    assert "- Time with a model request open, the lower bound: 1.000000 GPU-hours, 2.000000 EUR\n" in text
    assert "- Cost per task: 2.000000 EUR on wall-clock, 1.000000 EUR as the lower bound\n" in text
    assert text.index("- Wall-clock,") < text.index("- Time with a model request open")


def test_no_price_means_no_cost_but_the_hours_stay() -> None:
    run_cost = cost(run_data(), None)
    assert run_cost.wall_clock.hours == pytest.approx(0.025), "90 seconds"
    assert run_cost.wall_clock.eur is None and run_cost.request_time.eur is None
    assert "GPU_EUR_PER_HOUR is not set" in run_cost.notes
    text = render_markdown(run_data(), None, {})
    assert f"Price: {NOT_MEASURED}" in text
    assert f"Cost per task: {NOT_MEASURED}" in text
    assert f"0.025000 GPU-hours, {NOT_MEASURED}" in text


def test_a_partly_cached_run_has_no_cost_per_task() -> None:
    # Task b was all fresh, task a all cached: dividing by both tasks would show half the real cost.
    data = run_data(phases=(phase("arc1/a", None, 0, 32), phase("arc1/b", 1000, 32, 0)))
    run_cost = cost(data, 2.0)
    assert run_cost.wall_clock.eur_per_task is None and run_cost.request_time.eur_per_task is None
    assert run_cost.wall_clock.eur == pytest.approx(0.05), "the run's own figures still stand"
    assert run_cost.request_time.eur == pytest.approx(2.0 / 3600)
    assert "32 of 64 completions came from the cache" in " ".join(run_cost.notes)
    assert f"Cost per task: {NOT_MEASURED}\n" in render_markdown(data, 2.0, {})
    assert "covers 32 of 64" in time_split(data)[0].note


def test_one_cached_completion_is_enough_to_withhold_cost_per_task() -> None:
    data = run_data(phases=(phase("arc1/a", 1000, 31, 1), phase("arc1/b", 1000, 32, 0)))
    assert cost(data, 2.0).request_time.eur_per_task is None


def test_the_cached_note_survives_a_missing_price() -> None:
    data = run_data(phases=(phase("arc1/a", 1000, 8, 24),))
    notes = " ".join(cost(data, None).notes)
    assert "GPU_EUR_PER_HOUR is not set" in notes and "24 of 32 completions came from the cache" in notes
    text = render_markdown(data, None, {})
    assert "- Note: 24 of 32 completions came from the cache" in text


@pytest.mark.parametrize(
    ("status", "finished_at"),
    [("failed", STARTED + timedelta(hours=1)), ("interrupted", STARTED + timedelta(hours=1)), ("running", None)],
)
def test_a_run_that_did_not_finish_has_no_wall_clock_cost(status: str, finished_at: datetime | None) -> None:
    data = run_data(run=SolveRun("r1", SETTINGS, status, None, STARTED, finished_at))
    run_cost = cost(data, 2.0)
    assert (run_cost.wall_clock.hours, run_cost.wall_clock.eur, run_cost.wall_clock.eur_per_task) == (None, None, None)
    assert run_cost.request_time.eur_per_task is not None, "the requests it logged are still a lower bound"
    assert "a run that did not finish has no wall-clock cost" in run_cost.notes
    text = render_markdown(data, 2.0, {})
    assert f"- Wall-clock, what a rented GPU costs for this run: {NOT_MEASURED}\n" in text
    assert f"- Cost per task: {NOT_MEASURED} on wall-clock, " in text


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
