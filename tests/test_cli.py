"""`vora-arc run-solution`: the verdict a person sees and the exit code scripts rely on.

The sandbox is faked; what is under test is the lookup, the re-run that
catches nondeterminism, and the report.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from vora_arc import cli
from vora_arc.model import BatchResult, Grid, GridResult, GridStatus, RunStatus

TASK_JSON = {
    "train": [{"input": [[1, 2]], "output": [[2, 1]]}],
    "test": [{"input": [[3, 4]], "output": [[4, 3]]}],
}
PROGRAM = "def transform(grid):\n    return [row[::-1] for row in grid]\n"


def batch(train_output: Grid, test_output: Grid = ((4, 3),)) -> BatchResult:
    grids = (
        GridResult(0, False, GridStatus.OK, train_output, None, 1),
        GridResult(1, True, GridStatus.OK, test_output, None, 1),
    )
    return BatchResult("t/p", "sha", RunStatus.COMPLETED, grids, "sbx_1", 900, 120, 1 << 20, 30, "")


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    split = tmp_path / "data" / "arc1" / "training"
    split.mkdir(parents=True)
    (split / "abcd1234.json").write_text(json.dumps(TASK_JSON))
    (tmp_path / "solution.py").write_text(PROGRAM)

    @contextlib.asynccontextmanager
    async def fake_connect(profile: Any) -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(cli, "connect", fake_connect)
    yield tmp_path


def sandbox_returns(monkeypatch: pytest.MonkeyPatch, *results: BatchResult) -> list[str]:
    calls: list[str] = []
    queue = list(results)

    async def fake_run_batch(vora: Any, profile: Any, program: str, task: Any, *, correlation_id: str) -> BatchResult:
        calls.append(correlation_id)
        return queue.pop(0)

    monkeypatch.setattr(cli, "run_batch", fake_run_batch)
    return calls


def run_solution(root: Path) -> int:
    return cli.main(
        ["run-solution", "--task", "abcd1234", "--program", str(root / "solution.py"), "--data-dir", str(root / "data")]
    )


def test_a_correct_program_passes_after_a_second_identical_run(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = sandbox_returns(monkeypatch, batch(((2, 1),)), batch(((2, 1),)))
    assert run_solution(workspace) == 0
    assert calls == ["abcd1234/solution", "abcd1234/solution/rerun"], "a pass is only trusted after a re-run"
    out = capsys.readouterr().out
    assert "verdict: passed" in out
    assert "sandbox=sbx_1" in out


def test_a_pass_whose_rerun_differs_is_nondeterministic(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sandbox_returns(monkeypatch, batch(((2, 1),)), batch(((2, 1),), test_output=((0, 0),)))
    assert run_solution(workspace) == 1


def test_a_wrong_program_fails_without_a_rerun(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = sandbox_returns(monkeypatch, batch(((2, 2),)))
    assert run_solution(workspace) == 1
    assert len(calls) == 1
    out = capsys.readouterr().out
    assert "verdict: failed" in out
    assert "cell accuracy: 0.500" in out


def test_an_unknown_task_names_the_download_script(workspace: Path) -> None:
    with pytest.raises(SystemExit, match="download_data.sh"):
        cli.main(["run-solution", "--task", "missing", "--program", "x.py", "--data-dir", str(workspace / "data")])
