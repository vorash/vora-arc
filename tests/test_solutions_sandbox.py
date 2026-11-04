"""Milestone 1's done-when: every hand-written solution passes inside a real sandbox.

tests/test_solutions.py proves the solutions are right on the host, so a
failure here is a harness bug (runner, image, client or limits), not a wrong
solution.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vora_arc.cli import find_task, judge
from vora_arc.client import connect
from vora_arc.model import Verdict
from vora_arc.profile import load_profile
from vora_arc.tasks import load_task

ROOT = Path(__file__).resolve().parents[1]
SOLUTIONS = sorted((ROOT / "solutions").glob("*.py"))

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(
        not (os.environ.get("VORA_API_URL") and os.environ.get("VORA_API_KEY")),
        reason="needs a Vora sandbox host: set VORA_API_URL and VORA_API_KEY",
    ),
    pytest.mark.skipif(not (ROOT / "data" / "arc1").is_dir(), reason="run scripts/download_data.sh"),
]


@pytest.mark.parametrize("solution", SOLUTIONS, ids=[path.stem for path in SOLUTIONS])
async def test_solution_passes_in_the_sandbox(solution: Path) -> None:
    profile = load_profile()
    task = load_task(find_task(ROOT / "data", "arc1", solution.stem))
    async with connect(profile) as vora:
        outcome, runs = await judge(vora, profile, task, solution.read_text(), f"{task.id}/m1")
    assert outcome.verdict is Verdict.PASSED, runs
