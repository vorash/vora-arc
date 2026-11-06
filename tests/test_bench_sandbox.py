"""`vora-arc bench` on a real Vora host: a short run of each arm, so the wiring is proven.

These runs are too short to be results. docs/experiment-1.md has the commands for the real experiment.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vora_arc import cli
from vora_arc.bench import load_raw
from vora_arc.client import PoolMode

ROOT = Path(__file__).resolve().parents[1]

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(
        not (os.environ.get("VORA_API_URL") and os.environ.get("VORA_API_KEY")),
        reason="needs a Vora sandbox host: set VORA_API_URL and VORA_API_KEY",
    ),
    pytest.mark.skipif(not (ROOT / "data" / "arc1").is_dir(), reason="run scripts/download_data.sh"),
]


def bench(mode: PoolMode, raw: Path) -> int:
    args = ["bench", "--mode", mode.value, "--candidates", "16", "--warmup", "4", "--concurrency", "2", "--raw", str(raw)]
    return cli.main([*args, "--data-dir", str(ROOT / "data"), "--program", str(ROOT / "solutions" / "3c9b0459.py")])


@pytest.mark.parametrize("mode", [PoolMode.COLD, PoolMode.WARM])
def test_an_arm_runs_the_program_every_time_and_in_its_shape(mode: PoolMode, tmp_path: Path) -> None:
    raw = tmp_path / "raw.jsonl"

    assert bench(mode, raw) == 0

    summary = load_raw(raw).arms[0]
    assert (summary.ok, summary.failed, summary.off_shape, summary.wrong_reuse) == (16, 0, 0, 0)
    assert summary.distinct_outputs == 1
    assert summary.wall.count == 16


@pytest.mark.skipif(not os.environ.get("VORA_ADMIN_API_KEY"), reason="needs VORA_ADMIN_API_KEY and an unsafe grant")
def test_the_no_reset_arm_skips_every_reset(tmp_path: Path) -> None:
    raw = tmp_path / "raw.jsonl"

    assert bench(PoolMode.WARM_NO_RESET, raw) == 0

    summary = load_raw(raw).arms[0]
    assert (summary.ok, summary.off_shape, summary.wrong_reuse) == (16, 0, 0)
    assert summary.reset.count == 0
