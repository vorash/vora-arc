"""`vora-arc solve` end to end: fake model, throwaway PostgreSQL, and real Vora sandboxes.

The fake model replaces only the GPU. Every program here really runs, inside a sandbox,
hostile ones included.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fake_model import FakeModel, fenced

from vora_arc import cli
from vora_arc.client import connect
from vora_arc.profile import load_profile

ROOT = Path(__file__).resolve().parents[1]
HOSTILE = ROOT / "tests" / "hostile"
REAL_TASK = "3c9b0459"

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(
        not (os.environ.get("VORA_API_URL") and os.environ.get("VORA_API_KEY")),
        reason="needs a Vora sandbox host: set VORA_API_URL and VORA_API_KEY",
    ),
]

REVERSE = "def transform(grid):\n    return [row[::-1] for row in grid]\n"
REVERSE_LONGER = "def transform(grid):\n    # the same rule again\n    return [list(reversed(row)) for row in grid]\n"
WRONG_ON_TEST = "def transform(grid):\n    return [[0, 0]] if grid[0][0] == 5 else [row[::-1] for row in grid]\n"
IDENTITY = "def transform(grid):\n    return grid\n"
CRASHES = "def transform(grid):\n    raise ValueError('no rule')\n"
INVALID = "def transform(grid):\n    return [[11]]\n"
MEMORIZED = "def transform(grid):\n    return {2: [[1, 2]], 3: [[4, 3]]}.get(grid[0][0], grid)\n"
RANDOM_ON_TEST = (
    "import os\n"
    "def transform(grid):\n"
    "    if grid[0][0] == 5:\n"
    "        return [[b % 10 for b in os.urandom(30)] for _ in range(30)]\n"
    "    return [row[::-1] for row in grid]\n"
)
JUNK = "I could not work out the rule."

MIXED_TASK = {
    "train": [{"input": [[2, 1]], "output": [[1, 2]]}, {"input": [[3, 4]], "output": [[4, 3]]}],
    "test": [{"input": [[5, 6]], "output": [[6, 5]]}],
}
# Each sample's program, and the verdict it must get on MIXED_TASK. Sixteen samples
# give the report one measured point on its candidate-count chart.
MIXED_SAMPLES = [
    (REVERSE, "passed"),
    (REVERSE, "passed"),
    (REVERSE, "passed"),
    (REVERSE_LONGER, "passed"),
    (WRONG_ON_TEST, "passed"),
    (JUNK, "unparseable"),
    (JUNK, "unparseable"),
    (JUNK, "unparseable"),
    (IDENTITY, "failed"),
    (IDENTITY, "failed"),
    (CRASHES, "crashed"),
    (INVALID, "invalid"),
    (MEMORIZED, "memorized"),
    (RANDOM_ON_TEST, "nondeterministic"),
    ((HOSTILE / "infinite_loop.py").read_text(), "timeout"),
    ((HOSTILE / "allocate_2gb.py").read_text(), "crashed"),
]

REFINED_TASK = {
    "train": [{"input": [[7, 8, 9]], "output": [[9, 8, 7]]}, {"input": [[1, 2, 3]], "output": [[3, 2, 1]]}],
    "test": [{"input": [[4, 4, 6]], "output": [[6, 4, 4]]}],
}
KEEPS_MIDDLE_ONLY = "def transform(grid):\n    return [[0, row[1], 0] for row in grid]\n"


def as_completion(program: str) -> str:
    return program if program == JUNK else fenced(program)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    split = tmp_path / "data" / "arc1" / "training"
    split.mkdir(parents=True)
    (split / "e2e00001.json").write_text(json.dumps(MIXED_TASK))
    (split / "e2e00002.json").write_text(json.dumps(REFINED_TASK))
    real = ROOT / "data" / "arc1" / "training" / f"{REAL_TASK}.json"
    if real.exists():
        shutil.copy(real, split)
    return tmp_path / "data"


def canned(prompt: str) -> list[str]:
    if "Example 1 input:\n7 8 9" in prompt:
        return [fenced(REVERSE)] if "These programs were tried" in prompt else [fenced(KEEPS_MIDDLE_ONLY), fenced(IDENTITY)]
    if "Example 1 input:\n2 1" in prompt:
        return [as_completion(program) for program, _ in MIXED_SAMPLES]
    return [fenced((ROOT / "solutions" / f"{REAL_TASK}.py").read_text())]


def query(url: str, sql: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(sql.encode()).fetchall()


async def live_sandboxes(ids: set[str]) -> set[str]:
    async with connect(load_profile()) as vora:
        return {sandbox.id for sandbox in await vora.sandboxes.list()} & ids


def test_solve_runs_every_kind_of_program_in_real_sandboxes(
    data_dir: Path,
    tmp_path: Path,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    server = FakeModel(canned)
    samples = len(MIXED_SAMPLES)
    with server.running():
        monkeypatch.setenv("VLLM_URL", server.url)
        monkeypatch.setenv("VLLM_MODEL", "fake-model")
        monkeypatch.setenv("VORA_ARC_DATABASE_URL", database_url)
        monkeypatch.setenv("VORA_MAX_CONCURRENCY", "4")
        monkeypatch.setenv("GPU_EUR_PER_HOUR", "2.5")
        args = ["solve", "--split", "training", "--samples", str(samples), "--refine", "--data-dir", str(data_dir)]
        assert cli.main(args) == 0, capsys.readouterr().err
        first_requests = len(server.requests)
        run_id = query(database_url, "SELECT id FROM solve_runs")[0][0]
        (tmp_path / "results").mkdir()
        assert cli.main(["report", "--run", run_id, "--out", str(tmp_path / "results")]) == 0

        verdicts = query(
            database_url,
            "SELECT verdict FROM candidates WHERE task_id = 'arc1/e2e00001' AND round = 1 ORDER BY sample_index",
        )
        assert [v for v, in verdicts] == [verdict for _, verdict in MIXED_SAMPLES]
        assert query(database_url, "SELECT count(*) FROM candidates WHERE verdict IS NULL") == [(0,)]

        answers = query(
            database_url,
            "SELECT rank, votes, correct, output_json FROM answers WHERE task_id = 'arc1/e2e00001' ORDER BY rank",
        )
        assert [(rank, votes, correct) for rank, votes, correct, _ in answers] == [(1, 4, True), (2, 1, False)]
        assert answers[0][3] == [[[6, 5]]]

        distinct = len({program for program, _ in MIXED_SAMPLES if program != JUNK})
        survivors = len({program for program, verdict in MIXED_SAMPLES if verdict in ("passed", "nondeterministic")})
        runs = query(
            database_url,
            "SELECT count(*), count(DISTINCT r.candidate_id) FROM runs r JOIN candidates c ON c.id = r.candidate_id "
            "WHERE c.task_id = 'arc1/e2e00001'",
        )
        assert runs == [(distinct + survivors, distinct)], "one job per distinct program, plus re-runs of survivors"

        measured = query(
            database_url,
            "SELECT bool_and(startup_ms > 0), bool_and(exec_ms > 0), bool_and(warm_start = false), "
            "bool_and(reset_ms IS NULL), bool_and(audit_log_id IS NULL) FROM runs",
        )
        assert measured == [(True, True, True, True, True)]

        refined = query(
            database_url,
            "SELECT round, verdict, cell_accuracy FROM candidates WHERE task_id = 'arc1/e2e00002' ORDER BY round, sample_index",
        )
        assert refined[-1][:2] == (2, "passed"), refined
        assert query(database_url, "SELECT round, correct FROM answers WHERE task_id = 'arc1/e2e00002'") == [(2, True)]
        close = [accuracy for round_number, verdict, accuracy in refined if round_number == 1 and verdict == "failed"]
        assert close and all(accuracy is not None for accuracy in close)
        prompts = [request["messages"][-1]["content"] for request in server.requests]
        round_two = [prompt for prompt in prompts if "These programs were tried" in prompt]
        assert len(round_two) == 1 and KEEPS_MIDDLE_ONLY in round_two[0] and "[0]" in round_two[0]

        real_data = (ROOT / "data" / "arc1" / "training" / f"{REAL_TASK}.json").exists()
        if real_data:
            assert query(database_url, f"SELECT correct FROM answers WHERE task_id = 'arc1/{REAL_TASK}'") == [(True,)]

        text = (tmp_path / "results" / run_id / "report.md").read_text()
        assert "fake-model" in text
        assert "| 16 | 3 / 3 (100.0%) |" not in text, "the refined task isn't solved on round 1 samples"
        assert f"| 16 | {'2 / 3 (66.7%)' if real_data else '1 / 2 (50.0%)'} |" in text
        assert "| 32 | not measured |" in text, "the run took 16 samples per task"
        for chart in ("verdicts.png", "accuracy_vs_candidates.png"):
            assert (tmp_path / "results" / run_id / chart).exists()

        sandbox_ids = {
            sandbox for sandbox, in query(database_url, "SELECT DISTINCT result_json ->> 'sandbox_id' FROM runs")
        }
        assert sandbox_ids, "real runs have sandbox ids"
        assert asyncio.run(live_sandboxes(sandbox_ids)) == set(), "every sandbox was destroyed"

        assert cli.main(args) == 0
        assert len(server.requests) == first_requests, "the second run judges again but must not pay the model again"
