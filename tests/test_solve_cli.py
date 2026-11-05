"""`vora-arc solve` and `report` on a real PostgreSQL and the fake model, with canned sandbox results."""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from canned_runs import CLOSE, GOOD, JUNK, WRONG, CannedRuns, completions
from fake_model import FakeModel
from vora import VoraError

from vora_arc import cli, generate, schedule
from vora_arc.report import NOT_MEASURED

GRID_TASK = {
    "train": [{"input": [[1, 2]], "output": [[2, 1]]}, {"input": [[3, 4]], "output": [[4, 3]]}],
    "test": [{"input": [[5, 6]], "output": [[6, 5]]}],
}


class Solver:
    def __init__(self, root: Path, model: FakeModel, runs: CannedRuns) -> None:
        self.root, self.model, self.runs = root, model, runs

    def solve(self, *extra: str) -> int:
        return cli.main(["solve", "--split", "training", "--data-dir", str(self.root), *extra])

    def report(self, run_id: str) -> str:
        assert cli.main(["report", "--run", run_id, "--out", str(self.root / "results")]) == 0
        return (self.root / "results" / run_id / "report.md").read_text()


@pytest.fixture
def solver(tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Solver]:
    split = tmp_path / "arc1" / "training"
    split.mkdir(parents=True)
    for name in ("aaaa0001", "bbbb0002", "cccc0003"):
        (split / f"{name}.json").write_text(json.dumps(GRID_TASK))

    @contextlib.asynccontextmanager
    async def fake_connect(profile: Any) -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(cli, "connect", fake_connect)
    monkeypatch.setattr(generate, "RETRY_DELAYS_S", (0.0,))
    monkeypatch.delenv("GPU_EUR_PER_HOUR", raising=False)
    server = FakeModel(lambda prompt: completions(GOOD, GOOD, WRONG, JUNK))
    with server.running():
        monkeypatch.setenv("VLLM_URL", server.url)
        monkeypatch.setenv("VLLM_MODEL", "fake-model")
        monkeypatch.setenv("VORA_ARC_DATABASE_URL", database_url)
        yield Solver(tmp_path, server, CannedRuns(monkeypatch))


def run_ids(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [line.split()[1].rstrip(":") for line in capsys.readouterr().out.splitlines() if line.startswith("run ")][::2]


def query(url: str, sql: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(sql.encode()).fetchall()


def test_a_run_stores_every_result_and_a_report_reads_them(
    solver: Solver, database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert solver.solve("--samples", "4", "--limit", "2") == 0
    run_id = run_ids(capsys)[0]
    assert query(database_url, "SELECT id, status FROM solve_runs") == [(run_id, "finished")]
    assert query(database_url, "SELECT count(*) FROM candidates") == [(8,)], "--limit 2 tasks of 4 samples"
    assert query(database_url, "SELECT id FROM tasks ORDER BY id") == [("arc1/aaaa0001",), ("arc1/bbbb0002",)]
    assert query(database_url, "SELECT DISTINCT votes, correct FROM answers") == [(2, True)]

    text = solver.report(run_id)
    assert "Overall, 2 attempts | 2 / 2 (100.0%)" in text
    assert "| passed | 4 |" in text and "| failed | 2 |" in text and "| unparseable | 2 |" in text
    assert f"| 64 | {NOT_MEASURED} |" in text
    assert "Price: not measured" in text
    assert "fake-model" in text
    assert (solver.root / "results" / run_id / "verdicts.png").exists()


def test_a_second_run_pays_for_nothing_and_its_report_says_so(
    solver: Solver, database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert solver.solve("--samples", "4", "--limit", "1") == 0
    assert len(solver.model.requests) == 1
    assert solver.solve("--samples", "4", "--limit", "1") == 0
    assert len(solver.model.requests) == 1, "the second run must make no model request"

    first, second = run_ids(capsys)
    assert first != second
    assert query(database_url, "SELECT count(DISTINCT run_id) FROM candidates") == [(2,)]
    text = solver.report(second)
    assert "all 4 completions came from the cache" in text
    assert f"Cost per task: {NOT_MEASURED}" in text
    assert "Overall, 2 attempts | 1 / 1 (100.0%)" in text, "cached samples still get judged and voted on"


def test_a_larger_run_requests_only_the_samples_it_lacks(solver: Solver) -> None:
    assert solver.solve("--samples", "4", "--limit", "1") == 0
    solver.model.requests.clear()
    assert solver.solve("--samples", "6", "--limit", "1") == 0
    assert [request["n"] for request in solver.model.requests] == [2]


def test_refine_records_round_two(solver: Solver, database_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    solver.model.canned = lambda prompt: (
        completions(GOOD) if "These programs were tried" in prompt else completions(WRONG, CLOSE)
    )
    assert solver.solve("--samples", "2", "--limit", "1", "--refine") == 0
    assert query(database_url, "SELECT round, count(*) FROM candidates GROUP BY round ORDER BY round") == [(1, 2), (2, 1)]
    assert query(database_url, "SELECT round, correct FROM answers") == [(2, True)]
    text = solver.report(run_ids(capsys)[0])
    assert "Overall, 2 attempts | 1 / 1 (100.0%)" in text
    assert "Round 1, of all tasks | 0 / 1 (0.0%)" in text
    assert "Round 2, of the tasks it refined | 1 / 1 (100.0%)" in text


def test_a_model_outage_fails_the_run_keeps_earlier_tasks_and_the_next_run_resumes(
    solver: Solver, database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert solver.solve("--samples", "4", "--limit", "1") == 0
    solver.model.faults.extend([500] * 2)
    assert solver.solve("--samples", "4", "--limit", "2") == 1, "the first task is cached, the second hits the outage"

    failed = query(database_url, "SELECT id, error FROM solve_runs WHERE status = 'failed'")
    assert len(failed) == 1 and "gave up" in failed[0][1]
    assert query(database_url, f"SELECT DISTINCT task_id FROM candidates WHERE run_id = '{failed[0][0]}'") == [
        ("arc1/aaaa0001",)
    ], "the task finished before the outage is kept"
    text = solver.report(failed[0][0])
    assert "did not finish" in text and "what it logged: 1 tasks" in text
    assert "failed" in capsys.readouterr().err

    solver.model.requests.clear()
    assert solver.solve("--samples", "4", "--limit", "2") == 0
    assert [request["n"] for request in solver.model.requests] == [4], "only the task the outage interrupted"


def test_a_vora_failure_is_reported_and_exits_non_zero(
    solver: Solver, database_url: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(*args: Any, **kwargs: Any) -> Any:
        raise VoraError("503 Service Unavailable")

    monkeypatch.setattr(schedule, "run_batch", down)
    assert solver.solve("--samples", "4", "--limit", "1") == 1
    assert "Vora failed on 3 candidates" in capsys.readouterr().err
    assert query(database_url, "SELECT count(*) FROM candidates WHERE verdict IS NULL AND infra_error IS NOT NULL") == [(3,)]


def test_an_unknown_run_is_an_error(solver: Solver) -> None:
    with pytest.raises(SystemExit, match="no run nope"):
        solver.report("nope")


@pytest.mark.parametrize("missing", ["VLLM_URL", "VLLM_MODEL", "VORA_ARC_DATABASE_URL"])
def test_missing_settings_are_named_before_any_work(
    solver: Solver, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing)
    with pytest.raises(SystemExit, match=missing):
        solver.solve("--samples", "4")
    assert solver.model.requests == []


def test_samples_must_be_positive(solver: Solver) -> None:
    with pytest.raises(SystemExit):
        solver.solve("--samples", "0")
