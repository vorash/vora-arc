"""The store on a real PostgreSQL. Needs the `postgres` fixture's throwaway cluster."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from functools import partial
from typing import Any

import httpx
import psycopg
import pytest
from canned_runs import (
    CLOSE,
    CRASHES,
    FLAKY,
    GOOD,
    GOOD_LONGER,
    HANGS,
    JUNK,
    MEMORIZED,
    TASK,
    WRONG,
    WRONG_ANSWER_PASSES,
    CannedRuns,
    batch,
    completions,
)
from fake_model import FakeModel

from vora_arc import model
from vora_arc.generate import ModelConfig, extract_program, sample
from vora_arc.model import GridResult, GridStatus, Pair, Task, Verdict
from vora_arc.pipeline import CandidateResult, TaskResult, solve_task
from vora_arc.report import accuracy, accuracy_by_count, render_markdown, verdict_counts
from vora_arc.schedule import schedule
from vora_arc.store import RunSettings, Store, open_store, task_key
from vora_arc.vote import Answer

KEY = task_key("arc1", TASK)
SETTINGS = RunSettings("arc1", "training", None, 4, False, "m", "python-arc", "gvisor", 4)


async def solve(store: Store, canned: list[str], key: str = KEY, task: Task = TASK) -> TaskResult:
    server = FakeModel(lambda prompt: canned)
    await store.register_task(key, "arc1", "training")

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
            await store.register_task(KEY, "arc1", "training")
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
        await store.register_task(KEY, "arc1", "training")
        await store.save_completions(KEY, "h", "m", {0: "text", 1: "more"})
    async with open_store(database_url) as store:
        assert await store.load_completions(KEY, "h") == {0: "text", 1: "more"}


async def test_the_cache_separates_tasks_prompts_and_samples(database_url: str) -> None:
    other = "arc2/other"
    async with open_store(database_url) as store:
        await store.register_task(KEY, "arc1", "training")
        await store.register_task(other, "arc2", "training")
        await store.save_completions(KEY, "h1", "m", {0: "a", 1: "b"})
        await store.save_completions(KEY, "h2", "m", {0: "c"})
        await store.save_completions(other, "h1", "m", {0: "d"})
        assert await store.load_completions(KEY, "h1") == {0: "a", 1: "b"}
        assert await store.load_completions(KEY, "h2") == {0: "c"}
        assert await store.load_completions(other, "h1") == {0: "d"}


async def test_saving_a_completion_twice_keeps_the_first(database_url: str) -> None:
    async with open_store(database_url) as store:
        await store.register_task(KEY, "arc1", "training")
        assert await store.save_completions(KEY, "h", "m", {0: "first"}) == {0: "first"}
        assert await store.save_completions(KEY, "h", "m", {0: "second", 1: "new"}) == {0: "first", 1: "new"}
        assert await store.load_completions(KEY, "h") == {0: "first", 1: "new"}


async def test_two_runs_racing_for_a_sample_judge_the_one_text_that_is_stored(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    CannedRuns(monkeypatch)
    both_missed_the_cache = threading.Barrier(2, timeout=5)

    def canned(prompt: str) -> list[str]:
        both_missed_the_cache.wait()
        return completions(GOOD, WRONG)

    server = FakeModel(canned)

    async def solve_on(store: Store, http: httpx.AsyncClient) -> TaskResult:
        async def scheduler(task: Task, programs: Any) -> Any:
            return await schedule(None, None, task, programs, max_concurrency=4)  # type: ignore[arg-type]

        return await solve_task(
            TASK,
            sampler=partial(sample, http, ModelConfig(url=server.url, model="m"), store, KEY),
            scheduler=scheduler,
            samples=1,
            refine=False,
        )

    with server.running():
        async with open_store(database_url) as one, open_store(database_url) as other, httpx.AsyncClient(timeout=5.0) as http:
            await one.register_task(KEY, "arc1", "training")
            first, second = await asyncio.gather(solve_on(one, http), solve_on(other, http))
            for store, result in ((one, first), (other, second)):
                await store.save_task_result(await store.begin_run(SETTINGS), KEY, result)

    assert len(server.requests) == 2, "the race must really have happened: each run asked and got its own text"
    linked = rows(
        database_url,
        "SELECT c.program, co.text FROM candidates c "
        "JOIN completions co USING (task_id, prompt_hash, sample_index)",
    )
    assert len(linked) == 2
    assert all(program == extract_program(text) for program, text in linked), "a candidate must be the completion it points at"
    assert first.candidates[0].verdict is second.candidates[0].verdict
    assert first.answers == second.answers
    timings = first.timings[0], second.timings[0]
    assert [t.fresh_completions for t in timings] == [1, 1], "the loser paid for its request even though its text was dropped"


async def test_arc1_and_arc2_can_hold_the_same_id_with_different_grids(database_url: str) -> None:
    other = Task(id=TASK.id, train=(Pair(((9,),), ((9,),)),), test=(model.TestCase(((9,),), None),))
    async with open_store(database_url) as store:
        run_id = await store.begin_run(SETTINGS)
        for dataset, task in (("arc1", TASK), ("arc2", other)):
            key = task_key(dataset, task)
            await store.register_task(key, dataset, "evaluation")
            await store.save_task_result(run_id, key, TaskResult(task, (), (), 1, ()))
        data = await store.load_run(run_id)
    assert data is not None
    assert data.tasks == {task_key("arc1", TASK): TASK, task_key("arc2", other): other}


async def test_each_run_keeps_the_task_it_solved(database_url: str) -> None:
    corrected = replace(TASK, test=(model.TestCase(((5, 6),), ((9, 9),)),))
    async with open_store(database_url) as store:
        await store.register_task(KEY, "arc1", "training")
        before = await store.begin_run(SETTINGS)
        await store.save_task_result(before, KEY, TaskResult(TASK, (), (), 1, ()))
        after = await store.begin_run(SETTINGS)
        await store.save_task_result(after, KEY, TaskResult(corrected, (), (), 1, ()))
        first, second = await store.load_run(before), await store.load_run(after)
    assert first is not None and second is not None
    assert first.tasks[KEY] == TASK
    assert second.tasks[KEY] == corrected


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
    assert all(grid.is_test for grid in original.grids)
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


def candidates_with_every_grid(url: str, run_id: str) -> dict[tuple[int, int], tuple[GridResult, ...]]:
    """What load_run used to read: every grid of every candidate."""
    found = rows(
        url,
        "SELECT c.round, c.sample_index, r.result_json -> 'grids' FROM candidates c "
        "LEFT JOIN runs r ON r.candidate_id = COALESCE(c.duplicate_of, c.id) AND r.attempt = 1 "
        f"WHERE c.run_id = '{run_id}'",
    )
    return {
        (round_number, index): tuple(
            GridResult(
                g["index"],
                g["is_test"],
                GridStatus(g["status"]),
                None if g["output"] is None else tuple(tuple(row) for row in g["output"]),
                g["error"],
                g["wall_ms"],
            )
            for g in grids or ()
        )
        for round_number, index, grids in found
    }


async def test_loading_only_what_a_report_votes_on_changes_no_number(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    CannedRuns(monkeypatch)
    canned = completions(
        GOOD, GOOD, GOOD, GOOD_LONGER, WRONG_ANSWER_PASSES, WRONG_ANSWER_PASSES, WRONG, WRONG,
        CLOSE, CRASHES, HANGS, MEMORIZED, FLAKY, JUNK, JUNK, JUNK,
    )  # fmt: skip
    settings = replace(SETTINGS, samples=len(canned))
    async with open_store(database_url) as store:
        run_id = await store.begin_run(settings)
        await store.save_task_result(run_id, KEY, await solve(store, canned))
        await store.finish_run(run_id)
        data = await store.load_run(run_id)
    assert data is not None

    loaded = [g for c in data.candidates for g in c.grids]
    assert len(loaded) == 6 and all(g.is_test for g in loaded), "one test grid for each of six passed candidates"
    assert all(not c.grids for c in data.candidates if c.verdict is not Verdict.PASSED)
    assert data.candidates[1].is_duplicate and data.candidates[1].grids, "a duplicate still votes with its first copy's grids"

    assert [(r.solved, r.total) for r in accuracy(data)[:2]] == [(1, 1), (1, 1)]
    assert [(p.count, p.solved, p.total) for p in accuracy_by_count(data)] == [
        (16, 1, 1),
        (32, None, 1),
        (64, None, 1),
        (128, None, 1),
    ]
    assert verdict_counts(data) == {
        "unparseable": 3,
        "timeout": 1,
        "crashed": 1,
        "invalid": 0,
        "failed": 3,
        "memorized": 1,
        "nondeterministic": 1,
        "passed": 6,
    }

    every_grid = candidates_with_every_grid(database_url, run_id)
    assert sum(len(grids) for grids in every_grid.values()) > 3 * len(loaded), "the old read really held more"
    unfiltered = replace(data, candidates=tuple(replace(c, grids=every_grid[(c.round, c.sample_index)]) for c in data.candidates))
    assert render_markdown(data, 2.0, {}) == render_markdown(unfiltered, 2.0, {})


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
    assert data.candidates == () and data.runs == () and data.answers == () and data.tasks == {}


async def test_a_candidate_cannot_have_both_a_verdict_and_an_infra_error(database_url: str) -> None:
    async with open_store(database_url) as store:
        run_id = await store.begin_run(SETTINGS)
        await store.register_task(KEY, "arc1", "training")
        await store.save_completions(KEY, "h", "m", {0: "text"})
        both = CandidateResult(1, 0, "h", "p", None, Verdict.FAILED, 0.0, "error", ())
        with pytest.raises(psycopg.errors.CheckViolation):
            await store.save_task_result(run_id, KEY, TaskResult(TASK, (both,), (), 1, ()))


async def test_an_unknown_run_is_none(database_url: str) -> None:
    async with open_store(database_url) as store:
        assert await store.load_run("nope") is None


async def test_a_recorded_error_never_keeps_url_credentials(database_url: str) -> None:
    async with open_store(database_url) as store:
        run_id = await store.begin_run(SETTINGS)
        await store.finish_run(run_id, "BoomError: while calling https://user:p%40ss@gpu:8000/v1/chat/completions")
        data = await store.load_run(run_id)
    assert data is not None
    assert data.run.error == "BoomError: while calling https://gpu:8000/v1/chat/completions"


async def test_a_failed_run_records_why(database_url: str) -> None:
    async with open_store(database_url) as store:
        run_id = await store.begin_run(SETTINGS)
        await store.finish_run(run_id, "ModelError: down")
        data = await store.load_run(run_id)
    assert data is not None
    assert (data.run.status, data.run.error) == ("failed", "ModelError: down")
