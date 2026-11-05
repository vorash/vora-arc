"""One job per distinct program, under the cap, and a Vora failure is never a verdict."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from vora import VoraError

from vora_arc import model, schedule
from vora_arc.client import SandboxInfrastructureError
from vora_arc.model import (
    BatchResult,
    Grid,
    GridResult,
    GridStatus,
    Pair,
    RunStatus,
    Task,
    Verdict,
)
from vora_arc.schedule import (
    InfraFailure,
    Judgement,
    max_concurrency_from_env,
    program_sha256,
)

TASK = Task(id="t", train=(Pair(((1,),), ((2,),)),), test=(model.TestCase(((3,),), ((4,),)),))
PROFILE: Any = None


def batch(train: Grid = ((2,),), test: Grid = ((4,),)) -> BatchResult:
    grids = (GridResult(0, False, GridStatus.OK, train, None, 1), GridResult(1, True, GridStatus.OK, test, None, 1))
    return BatchResult("c", "s", RunStatus.COMPLETED, grids, "sb", 1, 1, None, None, "")


class FakeRuns:
    """Stands in for run_batch: canned results, nothing executed."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[str, str]] = []
        self.results: dict[str, list[BatchResult | Exception]] = {}
        self.running = 0
        self.peak = 0
        monkeypatch.setattr(schedule, "run_batch", self)

    async def __call__(self, vora: Any, profile: Any, program: str, task: Task, *, correlation_id: str) -> BatchResult:
        self.calls.append((program, correlation_id))
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(0.01)
        self.running -= 1
        queue = self.results.get(program)
        outcome = queue.pop(0) if queue else batch()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> FakeRuns:
    return FakeRuns(monkeypatch)


async def run(programs: list[str], cap: int = 4) -> dict[str, schedule.ProgramResult]:
    return await schedule.schedule(None, PROFILE, TASK, programs, max_concurrency=cap)  # type: ignore[arg-type]


async def test_each_distinct_program_is_one_job(runs: FakeRuns) -> None:
    runs.results = {"a": [batch(((9,),))], "b": [batch(((9,),))]}
    results = await run(["a", "b", "a", "a"])
    assert sorted(program for program, _ in runs.calls) == ["a", "b"]
    assert set(results) == {program_sha256("a"), program_sha256("b")}


@pytest.mark.parametrize("cap", [1, 3])
async def test_the_cap_limits_jobs_running_at_once(runs: FakeRuns, cap: int) -> None:
    await run([f"p{i}" for i in range(12)], cap=cap)
    assert runs.peak == cap, "more would overload the host, fewer would waste it"


async def test_waiting_for_a_slot_is_measured(runs: FakeRuns) -> None:
    results = await run([f"p{i}" for i in range(4)], cap=1)
    queue = sorted(r.queue_ms for r in results.values())
    assert queue[0] < 10 and queue[-1] >= 20


async def test_a_survivor_is_run_twice_and_a_failure_once(runs: FakeRuns) -> None:
    runs.results = {"good": [batch(), batch()], "wrong": [batch(((9,),))]}
    results = await run(["good", "wrong"])
    good = results[program_sha256("good")].result
    wrong = results[program_sha256("wrong")].result
    assert isinstance(good, Judgement) and isinstance(wrong, Judgement)
    assert good.outcome.verdict is Verdict.PASSED and len(good.runs) == 2
    assert wrong.outcome.verdict is Verdict.FAILED and len(wrong.runs) == 1
    assert good.verify_ms > 0


async def test_a_rerun_that_differs_on_a_test_input_is_nondeterministic(runs: FakeRuns) -> None:
    runs.results = {"flaky": [batch(), batch(test=((5,),))]}
    result = (await run(["flaky"]))[program_sha256("flaky")].result
    assert isinstance(result, Judgement) and result.outcome.verdict is Verdict.NONDETERMINISTIC


async def test_a_memorized_program_gets_no_rerun(runs: FakeRuns) -> None:
    program = "def transform(grid):\n    return [[2]]\n"
    result = (await run([program]))[program_sha256(program)].result
    assert isinstance(result, Judgement) and result.outcome.verdict is Verdict.MEMORIZED
    assert len(runs.calls) == 1


@pytest.mark.parametrize(
    "error", [SandboxInfrastructureError("stream broke"), VoraError("503")], ids=["infrastructure", "api"]
)
async def test_a_vora_failure_is_not_a_verdict_and_stops_nothing_else(runs: FakeRuns, error: Exception) -> None:
    runs.results = {"unlucky": [error]}
    results = await run(["unlucky", "fine"])
    assert isinstance(results[program_sha256("unlucky")].result, InfraFailure)
    fine = results[program_sha256("fine")].result
    assert isinstance(fine, Judgement) and fine.outcome.verdict is Verdict.PASSED


async def test_a_vora_failure_on_the_rerun_is_not_a_pass(runs: FakeRuns) -> None:
    runs.results = {"a": [batch(), SandboxInfrastructureError("gone")]}
    assert isinstance((await run(["a"]))[program_sha256("a")].result, InfraFailure)


async def test_a_bug_in_this_package_is_not_swallowed_as_a_vora_failure(runs: FakeRuns) -> None:
    runs.results = {"a": [KeyError("bug")]}
    with pytest.raises(KeyError):
        await run(["a"])


async def test_a_bug_in_one_job_cancels_its_siblings_and_waits_for_their_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []
    destroyed: list[str] = []
    all_running = asyncio.Event()

    async def run_batch(vora: Any, profile: Any, program: str, task: Task, *, correlation_id: str) -> BatchResult:
        started.append(program)
        if len(started) == 3:
            all_running.set()
        if program == "bug":
            await all_running.wait()
            raise KeyError("bug")
        try:
            await asyncio.sleep(60)
        finally:
            await asyncio.sleep(0.01)  # destroying a sandbox takes a request, even after a cancel
            destroyed.append(program)
        return batch()

    monkeypatch.setattr(schedule, "run_batch", run_batch)
    with pytest.raises(KeyError):
        await run(["sibling-1", "sibling-2", "bug", "queued"], cap=3)
    assert {"sibling-1", "sibling-2"} <= set(started)
    assert sorted(destroyed) == sorted(set(started) - {"bug"}), "a sandbox must not outlive the error, or the client closed next"
    assert asyncio.all_tasks() == {asyncio.current_task()}, "no job may keep running"


async def test_every_bug_stays_visible_when_several_jobs_fail(runs: FakeRuns) -> None:
    runs.results = {"a": [KeyError("first")], "b": [ValueError("second")]}
    with pytest.raises((KeyError, ValueError)) as raised:
        await run(["a", "b"])
    assert isinstance(raised.value.__cause__, ExceptionGroup), "the group holds what the first exception doesn't say"
    assert {type(e) for e in raised.value.__cause__.exceptions} == {KeyError, ValueError}


def test_the_cap_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VORA_MAX_CONCURRENCY", raising=False)
    assert max_concurrency_from_env() == schedule.DEFAULT_MAX_CONCURRENCY
    monkeypatch.setenv("VORA_MAX_CONCURRENCY", "3")
    assert max_concurrency_from_env() == 3
    for bad in ("0", "-1", "lots"):
        monkeypatch.setenv("VORA_MAX_CONCURRENCY", bad)
        with pytest.raises(SystemExit, match="VORA_MAX_CONCURRENCY"):
            max_concurrency_from_env()
