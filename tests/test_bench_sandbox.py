"""`vora-arc bench` on a real Vora host: a short corpus on each arm, so the wiring is proven.

These runs are too short to be results. docs/experiment-1.md has the commands for the real experiment.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vora_arc import cli
from vora_arc.bench_summary import load_raw
from vora_arc.client import PoolMode

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = 50

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(
        not (os.environ.get("VORA_API_URL") and os.environ.get("VORA_API_KEY")),
        reason="needs a Vora sandbox host: set VORA_API_URL and VORA_API_KEY",
    ),
    pytest.mark.skipif(not (ROOT / "data" / "arc1").is_dir(), reason="run scripts/download_data.sh"),
]


def bench(mode: PoolMode, raw: Path) -> int:
    args = ["bench", "--mode", mode.value, "--candidates", str(CANDIDATES), "--warmup", "4", "--concurrency", "2", "--raw", str(raw)]
    return cli.main([*args, "--data-dir", str(ROOT / "data"), "--solutions", str(ROOT / "solutions")])


@pytest.mark.parametrize("mode", [PoolMode.COLD, PoolMode.WARM])
def test_an_arm_judges_every_candidate_in_its_shape(mode: PoolMode, tmp_path: Path) -> None:
    raw = tmp_path / "raw.jsonl"

    assert bench(mode, raw) == 0

    summary = load_raw(raw).arms[0]
    assert (summary.judged, summary.infra_failed, summary.off_shape, summary.wrong_reuse) == (CANDIDATES, 0, 0, 0)
    assert summary.hand_written_not_passed == ()
    assert len(summary.verdicts) > 1, "a mixed corpus can't all earn one verdict"
    assert summary.wall.count == CANDIDATES


@pytest.mark.skipif(not os.environ.get("VORA_ADMIN_API_KEY"), reason="needs VORA_ADMIN_API_KEY and an unsafe grant")
def test_the_no_reset_arm_skips_every_reset(tmp_path: Path) -> None:
    raw = tmp_path / "raw.jsonl"

    assert bench(PoolMode.WARM_NO_RESET, raw) == 0

    summary = load_raw(raw).arms[0]
    assert (summary.judged, summary.off_shape, summary.wrong_reuse) == (CANDIDATES, 0, 0)
    assert summary.reset.count == 0
