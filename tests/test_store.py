"""The store on a real PostgreSQL. Needs the `postgres` fixture's throwaway cluster."""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from typing import Any

import httpx
import psycopg
import pytest
from canned_runs import (
    CLOSE,
    GOOD,
    JUNK,
    MEMORIZED,
    TASK,
    WRONG,
    CannedRuns,
    batch,
    completions,
)
from fake_model import FakeModel

from vora_arc import model
from vora_arc.generate import ModelConfig, sample
from vora_arc.model import Pair, Task, Verdict
from vora_arc.pipeline import CandidateResult, TaskResult, solve_task
from vora_arc.schedule import schedule
from vora_arc.store import RunSettings, Store, open_store, task_key
from vora_arc.vote import Answer

KEY = task_key("arc1", TASK)
SETTINGS = RunSettings("arc1", "training", None, 4, False, "m", "python-arc", "gvisor", 4)


async def solve(store: Store, canned: list[str], key: str = KEY, task: Task = TASK) -> TaskResult:
    server = FakeModel(lambda prompt: canned)
    await store.save_task_definition(key, "arc1", "training", task)

    async def scheduler(task: Task, programs: Any) -> Any:
        return await schedule(None, None, task, programs, max_concurrency=4)  # type: ignore[arg-type]

    with server.running():
        async with httpx.AsyncClient(timeout=5.0) as http:
            return await solve_task(
                task,
                sampler=partial(sample, http, ModelConfig(url=server.url, model="m"), store, key),
                scheduler=scheduler,
                samples=len(canned),
                refine=False,
            )


def rows(url: str, query: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(query.encode()).fetchall()


async def test_the_schema_can_be_applied_again(database_url: str) -> None:
    async with open_store(database_url) as store:
        await store.ensure_schema()


async def test_a_second_run_on_postgres_makes_no_model_request(database_url: str) -> None:
    server = FakeModel(lambda prompt: [f"completion {i}" for i in range(100)])
    with server.running():
        config = ModelConfig(url=server.url, model="m")
        async with open_store(database_url) as store, httpx.AsyncClient(timeout=5.0) as http:
            await store.save_task_definition(KEY, "arc1", "training", TASK)
            first = await sample(http, config, store, KEY, "p", 20)
            requests = len(server.requests)
            second = await sample(http, config, store, KEY, "p", 20)
    assert len(server.requests) == requests
    assert second.texts == first.texts
    assert second.fresh == 0
    stored = rows(database_url, "SELECT model, count(*) FROM completions GROUP BY model")
    assert stored == [("m", 20)]


async def test_a_new_connection_still_sees_the_cache(database_url: str) -> None:
    async with open_store(database_url) as store:
        await store.save_task_definition(KEY, "arc1", "training", TASK)
        await store.save_completions(KEY, "h", "m", {0: "text", 1: "more"})
    async with open_store(database_url) as store:
        assert await store.load_completions(KEY, "h") == {0: "text", 1: "more"}


async def test_the_cache_separates_tasks_prompts_and_samples(database_url: str) -> None:
    other = "arc2/other"
    async with open_store(database_url) as store:
        await store.save_task_definition(KEY, "arc1", "training", TASK)
        await store.save_task_definition(other, "arc2", "training", TASK)
        await store.save_completions(KEY, "h1", "m", {0: "a", 1: "b"})
        await store.save_completions(KEY, "h2", "m", {0: "c"})
        await store.save_completions(other, "h1", "m", {0: "d"})
        assert await store.load_completions(KEY, "h1") == {0: "a", 1: "b"}
        assert await store.load_completions(KEY, "h2") == {0: "c"}
        assert await store.load_completions(other, "h1") == {0: "d"}


async def test_saving_a_completion_twice_keeps_the_first(database_url: str) -> None:
    async with open_store(database_url) as store:
        await store.save_task_definition(KEY, "arc1", "training", TASK)
        await store.save_completions(KEY, "h", "m", {0: "first"})
        await store.save_completions(KEY, "h", "m", {0: "second"})
        assert await store.load_completions(KEY, "h") == {0: "first"}


async def test_arc1_and_arc2_can_hold_the_same_id_with_different_grids(database_url: str) -> None:
    other = Task(id=TASK.id, train=(Pair(((9,),), ((9,),)),), test=(model.TestCase(((9,),), None),))
    async with open_store(database_url) as store:
        await store.save_task_definition(task_key("arc1", TASK), "arc1", "evaluation", TASK)
        await store.save_task_definition(task_key("arc2", other), "arc2", "evaluation", other)
    assert len(rows(database_url, "SELECT id FROM tasks")) == 2


async def test_a_task_round_trips_with_and_without_test_outputs(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    CannedRuns(monkeypatch)
    hidden = Task(id="h1", train=TASK.train, test=(model.TestCase(((5, 6),), None),))
    async with open_store(database_url) as store:
        run_id = await store.begin_run(SETTINGS)
        result = await solve(store, completions(GOOD), key="arc1/h1", task=hidden)
        await store.save_task_result(run_id, "arc1/h1", result)
        data = await store.load_run(run_id)
    assert data is not None
    assert data.tasks["arc1/h1"] == hidden


async def test_a_task_result_is_stored_and_read_back(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    runs = CannedRuns(monkeypatch)
    async with open_store(database_url) as store:
        run_id = await store.begin_run(SETTINGS)
        result = await solve(store, completions(GOOD, GOOD, JUNK, WRONG, MEMORIZED))
        await store.save_task_result(run_id, KEY, result)
        await store.finish_run(run_id)
        data = await store.load_run(run_id)
    assert data is not None
    assert data.run.status == "finished" and data.run.finished_at is not None
    assert data.run.settings == SETTINGS
    assert data.tasks[KEY] == TASK
    assert [c.verdict for c in data.candidates] == [
        Verdict.PASSED,
        Verdict.PASSED,
        Verdict.UNPARSEABLE,
        Verdict.FAILED,
        Verdict.MEMORIZED,
    ]
    original, duplicate = data.candidates[:2]
    assert not original.is_duplicate and duplicate.is_duplicate
    assert duplicate.grids == original.grids != (), "a duplicate reads its first copy's result"
    assert data.candidates[2].grids == ()
    assert len(data.runs) == len(runs.programs) == 4, "good twice, wrong once, memorized once"
    assert [(a.rank, a.votes, a.correct, a.round) for a in data.answers] == [(1, 2, True, 1)]

    links = rows(
        database_url,
        "SELECT d.duplicate_of = o.id, o.duplicate_of IS NULL FROM candidates d "
        "JOIN candidates o ON o.sample_index = 0 WHERE d.sample_index = 1",
    )
    assert links == [(True, True)]
    measured = rows(database_url, "SELECT DISTINCT warm_start, reset_ms, audit_log_id FROM runs")
    assert measured == [(False, None, None)], "no pool: not warm, and nothing invented for reset or audit"
    accuracy = rows(database_url, "SELECT cell_accuracy FROM candidates WHERE verdict = 'failed'")
    assert accuracy == [(0.0,)]


async def test_two_runs_of_one_task_stay_apart_and_share_completions(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    CannedRuns(monkeypatch)
    canned = completions(GOOD, CLOSE)
    async with open_store(database_url) as store:
        first = await store.begin_run(SETTINGS)
        await store.save_task_result(first, KEY, await solve(store, canned))
        second = await store.begin_run(SETTINGS)
        await store.save_task_result(second, KEY, await solve(store, canned))
        first_data = await store.load_run(first)
        second_data = await store.load_run(second)
    assert first != second
    assert first_data is not None and second_data is not None
    assert len(first_data.candidates) == len(second_data.candidates) == 2
    assert len(first_data.answers) == len(second_data.answers) == 1
    assert rows(database_url, "SELECT count(*) FROM completions") == [(2,)]


async def test_text_from_a_hostile_program_cannot_break_a_save(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    CannedRuns(monkeypatch)
    async with open_store(database_url) as store:
        run_id = await store.begin_run(SETTINGS)
        result = await solve(store, completions(WRONG))
        run = replace(batch(train=(((1, 2),), ((3, 4),))), stderr_tail="nul \x00 and surrogate \ud800")
        hostile = replace(result.candidates[0], runs=(run,))
        await store.save_task_result(run_id, KEY, TaskResult(TASK, (hostile,), (), 1, ()))
    stored = rows(database_url, "SELECT result_json ->> 'stderr_tail' FROM runs")[0][0]
    assert stored.startswith("nul ") and "and surrogate" in stored


async def test_a_failed_save_leaves_nothing_of_that_task(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    CannedRuns(monkeypatch)
    async with open_store(database_url) as store:
        run_id = await store.begin_run(SETTINGS)
        result = await solve(store, completions(GOOD))
        answer = Answer(1, (((6, 5),),), 1, True)
        broken = TaskResult(TASK, result.candidates, (answer, answer), 1, result.timings)
        with pytest.raises(psycopg.errors.UniqueViolation):
            await store.save_task_result(run_id, KEY, broken)
        data = await store.load_run(run_id)
    assert data is not None
    assert data.candidates == () and data.runs == () and data.answers == ()


async def test_a_candidate_cannot_have_both_a_verdict_and_an_infra_error(database_url: str) -> None:
    async with open_store(database_url) as store:
        run_id = await store.begin_run(SETTINGS)
        await store.save_task_definition(KEY, "arc1", "training", TASK)
        await store.save_completions(KEY, "h", "m", {0: "text"})
        both = CandidateResult(1, 0, "h", "p", None, Verdict.FAILED, 0.0, "error", ())
        with pytest.raises(psycopg.errors.CheckViolation):
            await store.save_task_result(run_id, KEY, TaskResult(TASK, (both,), (), 1, ()))


async def test_an_unknown_run_is_none(database_url: str) -> None:
    async with open_store(database_url) as store:
        assert await store.load_run("nope") is None


async def test_a_failed_run_records_why(database_url: str) -> None:
    async with open_store(database_url) as store:
        run_id = await store.begin_run(SETTINGS)
        await store.finish_run(run_id, "ModelError: down")
        data = await store.load_run(run_id)
    assert data is not None
    assert (data.run.status, data.run.error) == ("failed", "ModelError: down")
