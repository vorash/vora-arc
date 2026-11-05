"""A task from samples to answers, over real HTTP to the fake model, with canned sandbox results."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from functools import partial

import httpx
import pytest
from canned_runs import (
    CLOSE,
    CLOSER,
    CRASHES,
    FLAKY,
    GOOD,
    GOOD_LONGER,
    HANGS,
    JUNK,
    MEMORIZED,
    RIGHT_TEST,
    TASK,
    WRONG,
    WRONG_ANSWER_PASSES,
    CannedRuns,
    completions,
)
from fake_model import DictCache, FakeModel

from vora_arc.generate import ModelConfig, sample
from vora_arc.model import Task, Verdict
from vora_arc.pipeline import TaskResult, solve_task
from vora_arc.schedule import ProgramResult, schedule


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        yield client


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> CannedRuns:
    return CannedRuns(monkeypatch)


async def solve(
    http: httpx.AsyncClient,
    first_round: Sequence[str],
    *,
    refine: bool = False,
    second_round: Sequence[str] = (JUNK,),
    samples: int | None = None,
    task: Task = TASK,
) -> tuple[TaskResult, FakeModel]:
    def canned(prompt: str) -> Sequence[str]:
        return second_round if "These programs were tried" in prompt else first_round

    server = FakeModel(canned)
    with server.running():
        result = await solve_task(
            task,
            sampler=partial(sample, http, ModelConfig(url=server.url, model="m"), DictCache(), task.id),
            scheduler=_scheduler,
            samples=len(first_round) if samples is None else samples,
            refine=refine,
        )
    return result, server


async def _scheduler(task: Task, programs: Sequence[str]) -> dict[str, ProgramResult]:
    return await schedule(None, None, task, programs, max_concurrency=4)  # type: ignore[arg-type]


async def test_each_kind_of_completion_gets_its_verdict(http: httpx.AsyncClient, runs: CannedRuns) -> None:
    programs = (GOOD, JUNK, WRONG, CRASHES, HANGS, FLAKY, MEMORIZED)
    result, _ = await solve(http, completions(*programs))
    assert [c.verdict for c in result.candidates] == [
        Verdict.PASSED,
        Verdict.UNPARSEABLE,
        Verdict.FAILED,
        Verdict.CRASHED,
        Verdict.TIMEOUT,
        Verdict.NONDETERMINISTIC,
        Verdict.MEMORIZED,
    ]
    wrong = result.candidates[2]
    assert wrong.cell_accuracy == 0.0
    assert result.candidates[1].program is None and result.candidates[1].runs == ()
    assert {c.round for c in result.candidates} == {1}


async def test_a_duplicate_links_to_its_first_copy_runs_nothing_and_still_votes(
    http: httpx.AsyncClient, runs: CannedRuns
) -> None:
    result, _ = await solve(http, completions(WRONG_ANSWER_PASSES, GOOD, GOOD, GOOD))
    assert sorted(runs.programs).count(GOOD) == 2, "one job plus its determinism re-run"
    first, *copies = result.candidates[1:]
    assert first.first_copy is None and len(first.runs) == 2
    for copy in copies:
        assert copy.first_copy == (1, 1)
        assert copy.runs == ()
        assert copy.verdict is Verdict.PASSED
    assert [(a.outputs, a.votes, a.correct) for a in result.answers][0] == ((RIGHT_TEST,), 3, True)
    assert result.answers[1].votes == 1


async def test_a_failed_duplicate_keeps_its_cell_accuracy(http: httpx.AsyncClient, runs: CannedRuns) -> None:
    result, _ = await solve(http, completions(CLOSE, CLOSE))
    assert result.candidates[1].cell_accuracy == result.candidates[0].cell_accuracy == 0.5


async def test_without_refine_a_task_with_no_pass_stops_after_one_round(http: httpx.AsyncClient, runs: CannedRuns) -> None:
    result, server = await solve(http, completions(WRONG))
    assert {c.round for c in result.candidates} == {1}
    assert len(server.requests) == 1
    assert result.answers == () and not result.solved


async def test_refine_samples_half_as_many_and_records_round_two(http: httpx.AsyncClient, runs: CannedRuns) -> None:
    first = completions(CLOSER, CLOSE, WRONG, JUNK)
    result, server = await solve(http, first, refine=True, second_round=completions(GOOD, GOOD_LONGER))
    prompts = [r["messages"][-1]["content"] for r in server.requests]
    assert len(prompts) == 2
    assert server.requests[1]["n"] == 2, "N/2 new candidates"
    assert "These programs were tried" in prompts[1]
    assert CLOSER in prompts[1] and CLOSE in prompts[1] and WRONG in prompts[1]
    assert "[3] [4]" in prompts[1], "wrong cells are marked"
    round_two = [c for c in result.candidates if c.round == 2]
    assert [c.verdict for c in round_two] == [Verdict.PASSED, Verdict.PASSED]
    assert result.answer_round == 2 and result.solved
    assert [t.round for t in result.timings] == [1, 2]


async def test_refine_shows_three_distinct_programs_not_three_copies(http: httpx.AsyncClient, runs: CannedRuns) -> None:
    first = completions(CLOSER, CLOSER, CLOSER, CLOSE, WRONG)
    _, server = await solve(http, first, refine=True)
    prompt = server.requests[1]["messages"][-1]["content"]
    assert prompt.count("cell accuracy") == 3
    assert CLOSE in prompt and WRONG in prompt


async def test_a_second_round_copy_of_a_round_one_program_is_not_run_again(
    http: httpx.AsyncClient, runs: CannedRuns
) -> None:
    result, _ = await solve(http, completions(CLOSE, CLOSE), refine=True, second_round=completions(CLOSE))
    assert runs.programs == [CLOSE]
    copy = result.candidates[-1]
    assert (copy.round, copy.first_copy, copy.verdict) == (2, (1, 0), Verdict.FAILED)


async def test_a_task_with_a_pass_is_not_refined(http: httpx.AsyncClient, runs: CannedRuns) -> None:
    _, server = await solve(http, completions(GOOD, WRONG), refine=True)
    assert len(server.requests) == 1


async def test_nothing_to_learn_from_means_no_second_round(http: httpx.AsyncClient, runs: CannedRuns) -> None:
    _, server = await solve(http, completions(JUNK, CRASHES), refine=True)
    assert len(server.requests) == 1, "refinement starts from failed candidates, and there are none"


async def test_a_nondeterministic_program_cannot_vote(http: httpx.AsyncClient, runs: CannedRuns) -> None:
    result, _ = await solve(http, completions(FLAKY))
    assert result.answers == ()


async def test_no_parseable_program_means_no_run_and_no_answers(http: httpx.AsyncClient, runs: CannedRuns) -> None:
    result, _ = await solve(http, [JUNK])
    assert runs.programs == [] and result.answers == ()
    timing = result.timings[0]
    assert (timing.scheduling_ms, timing.verification_ms) == (None, None), "nothing ran, so nothing was measured"
    assert timing.generation_ms is not None
