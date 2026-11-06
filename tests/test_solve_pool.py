"""`vora-arc solve --pool` end to end: fake model, real PostgreSQL, fake pool routes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fake_model import FakeModel, fenced
from fake_pools import TENANT_KEY, FakePools, Frames, stdout_frame

from vora_arc import cli

REVERSE = "def transform(grid):\n    return [row[::-1] for row in grid]\n"
TASK = {
    "train": [{"input": [[1, 2]], "output": [[2, 1]]}, {"input": [[3, 4]], "output": [[4, 3]]}],
    "test": [{"input": [[5, 6]], "output": [[6, 5]]}],
}


@pytest.fixture
def fake(tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakePools]:
    split = tmp_path / "arc1" / "training"
    split.mkdir(parents=True)
    (split / "aaaa0001.json").write_text(json.dumps(TASK))
    model = FakeModel(lambda prompt: [fenced(REVERSE)])
    server = FakePools()
    with model.running(), server.running():
        monkeypatch.setenv("VLLM_URL", model.url)
        monkeypatch.setenv("VLLM_MODEL", "fake-model")
        monkeypatch.setenv("VORA_ARC_DATABASE_URL", database_url)
        monkeypatch.setenv("VORA_MAX_CONCURRENCY", "2")
        monkeypatch.setenv("VORA_API_URL", server.url)
        monkeypatch.setenv("VORA_API_KEY", TENANT_KEY)
        yield server


def query(url: str, sql: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(sql.encode()).fetchall()


def solve(root: Path) -> int:
    return cli.main(["solve", "--pool", "--split", "training", "--samples", "1", "--data-dir", str(root)])


def test_solve_on_a_pool_stores_real_values_and_a_report_states_the_mix(
    fake: FakePools, tmp_path: Path, database_url: str
) -> None:
    right = stdout_frame(
        {"index": 0, "status": "OK", "output": [[2, 1]], "error": None, "wall_ms": 1},
        {"index": 1, "status": "OK", "output": [[4, 3]], "error": None, "wall_ms": 1},
        {"index": 2, "status": "OK", "output": [[6, 5]], "error": None, "wall_ms": 1},
        {"done": True, "stderr_tail": ""},
    )
    fake.runs.append(
        Frames(
            (
                {"run": {"sandboxId": "sbx_1", "startupMs": "185", "sandboxRun": 1}},
                right,
                {"exit": {"reason": "EXITED", "executionId": "exe_cold"}},
                {"runDone": {"outcome": "POOL_RESET_OK"}},
            )
        )
    )

    assert solve(tmp_path) == 0

    stored = query(database_url, "SELECT warm_start, reset_ms, audit_log_id, startup_ms >= 0 FROM runs ORDER BY attempt")
    assert stored[0] == (False, None, "exe_cold", True), "protojson left out resetMs, and that is NULL"
    assert stored[1][0] is True and stored[1][1] == 3 and stored[1][3] is True
    assert stored[1][2] is not None
    declared = fake.calls("PUT")[0]
    assert declared.body is not None and (declared.body["size"], declared.body["maxSize"]) == (2, 2)
    assert "reuse" not in declared.body, "solve never runs without a reset"
    assert len(fake.calls("DELETE")) == 1, "a finished solve gives its capacity back"

    run_id = query(database_url, "SELECT id FROM solve_runs")[0][0]
    assert cli.main(["report", "--run", run_id, "--out", str(tmp_path / "results")]) == 0
    text = (tmp_path / "results" / run_id / "report.md").read_text()
    assert "1 of 2 runs used a pool's running sandbox" in text
    assert "every run used a fresh sandbox" not in text


def test_solve_without_the_flag_uses_no_pool(fake: FakePools, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def no_cold_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("reached the cold path")

    monkeypatch.setattr("vora_arc.schedule.run_batch", no_cold_run)
    with pytest.raises(AssertionError, match="cold path"):
        cli.main(["solve", "--split", "training", "--samples", "1", "--data-dir", str(tmp_path)])
    assert fake.calls("PUT") == []
