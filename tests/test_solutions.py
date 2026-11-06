"""Ground truth for the sandbox: every hand-written solution is exactly right.

The solutions are trusted code, so they run here in-process. M1's sandbox run
must report `passed` for each of them; a mismatch there is a harness bug.
"""

import importlib.util
from collections.abc import Callable
from pathlib import Path

import pytest
from host_safety import violations

from vora_arc.model import BatchResult, Grid, GridResult, GridStatus, RunStatus, Task, Verdict
from vora_arc.tasks import load_task
from vora_arc.verify import Judged, verify

ROOT = Path(__file__).resolve().parents[1]
SOLUTIONS = sorted((ROOT / "solutions").glob("*.py"))
TRAINING = ROOT / "data" / "arc1" / "training"

needs_data = pytest.mark.skipif(
    not TRAINING.is_dir(), reason="ARC data not downloaded; run scripts/download_data.sh"
)
pytestmark = pytest.mark.usefixtures("host_safe_programs")

Transform = Callable[[list[list[int]]], list[list[int]]]


def load(path: Path) -> tuple[Task, Transform]:
    assert not violations(path.read_text()), f"{path} must not run on the host"
    spec = importlib.util.spec_from_file_location(f"solution_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    transform: Transform = module.transform
    return load_task(TRAINING / f"{path.stem}.json"), transform


def run(transform: Transform, grid: Grid) -> Grid:
    return tuple(tuple(row) for row in transform([list(row) for row in grid]))


def test_there_are_ten_solutions() -> None:
    assert len(SOLUTIONS) == 10


@needs_data
@pytest.mark.parametrize("path", SOLUTIONS, ids=lambda p: p.stem)
def test_solution_solves_every_train_and_test_pair(path: Path) -> None:
    task, transform = load(path)
    for i, pair in enumerate(task.train):
        assert run(transform, pair.input) == pair.output, f"train[{i}]"
    for i, case in enumerate(task.test):
        assert case.output is not None
        assert run(transform, case.input) == case.output, f"test[{i}]"


@needs_data
@pytest.mark.parametrize("path", SOLUTIONS, ids=lambda p: p.stem)
def test_solution_passes_verify_given_a_faithful_run(path: Path) -> None:
    # Catches a solution that verify would reject even with a perfect sandbox,
    # such as one holding a train output literal.
    task, transform = load(path)
    inputs = [(False, i, p.input) for i, p in enumerate(task.train)]
    inputs += [(True, i, c.input) for i, c in enumerate(task.test)]
    grids = tuple(
        GridResult(index=i, is_test=is_test, status=GridStatus.OK, output=run(transform, g), error=None, wall_ms=0)
        for is_test, i, g in inputs
    )
    result = BatchResult(
        correlation_id=f"{task.id}/hand",
        program_sha256="",
        run_status=RunStatus.COMPLETED,
        grids=grids,
        sandbox_id="in-process",
        startup_ms=0,
        exec_ms=0,
        peak_mem_bytes=None,
        cpu_ms=None,
        stderr_tail="",
    )
    assert verify(task, path.read_text(), result) == Judged(Verdict.PASSED)
