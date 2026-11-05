"""The Grafana dashboard asks only for metrics that exist, or says that they don't yet."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = json.loads((ROOT / "dashboards" / "vora-arc.json").read_text())
PANELS = [panel for panel in DASHBOARD["panels"] if panel["type"] != "row"]
VORA_METRICS = Path(os.environ.get("VORA_REPO", ROOT.parent / "vora")) / "internal" / "telemetry" / "metrics.go"

# Metric -> labels, from internal/telemetry/metrics.go. vora_<name>_seconds histograms take `le`.
EXPORTED: dict[str, set[str]] = {
    "vora_exec_total": {"status"},
    "vora_exec_duration_seconds": {"le"},
    "vora_exec_failed_total": {"reason"},
    "vora_sandbox_create_total": {"status"},
    "vora_sandbox_create_duration_seconds": {"le"},
    "vora_sandbox_failed_total": {"reason"},
    "vora_sandbox_running": set(),
    "vora_runner_sandboxes": set(),
    "vora_network_decisions_total": {"decision", "reason"},
    "vora_network_denied_total": set(),
    "vora_policy_denied_total": set(),
    "vora_audit_write_failed_total": set(),
}
# From the warm-pool design's metrics table. Vora's build step 13 adds them.
DESIGN_ONLY: dict[str, set[str]] = {
    "vora_pool_runs_total": {"pool", "start", "reason"},
    "vora_pool_run_duration_seconds": {"pool", "start", "le"},
    "vora_pool_startup_seconds": {"pool", "start", "le"},
    "vora_pool_reset_duration_seconds": {"pool", "result", "le"},
    "vora_pool_sandboxes": {"pool", "state"},
    "vora_pool_retired_total": {"pool", "cause"},
    "vora_pool_exhausted_total": {"pool"},
    "vora_pool_start_failed_total": {"pool"},
}


def metric_in(expr: str) -> str:
    match = re.search(r"\b(vora_\w+)", expr)
    assert match is not None, f"no Vora metric in {expr}"
    return match.group(1).removesuffix("_bucket")


def labels_in(expr: str) -> set[str]:
    return {label.strip() for group in re.findall(r"by \(([^)]*)\)", expr) for label in group.split(",")}


def exprs(panel: dict[str, Any]) -> list[str]:
    return [target["expr"] for target in panel["targets"]]


@pytest.mark.parametrize("panel", PANELS, ids=[panel["title"] for panel in PANELS])
def test_every_query_names_a_known_metric_with_its_real_labels(panel: dict[str, Any]) -> None:
    known = EXPORTED | DESIGN_ONLY
    for expr in exprs(panel):
        metric = metric_in(expr)
        assert metric in known, f"{metric} is not exported by Vora and not in the design"
        assert labels_in(expr) <= known[metric], f"{expr} groups by a label {metric} doesn't have"


def test_the_four_spec_sections_exist() -> None:
    rows = [panel["title"] for panel in DASHBOARD["panels"] if panel["type"] == "row"]
    assert rows == ["Throughput", "Latency", "Pool state", "Policy events"]


def test_a_panel_on_a_metric_vora_does_not_export_says_so() -> None:
    for panel in PANELS:
        if any(metric_in(expr) in DESIGN_ONLY for expr in exprs(panel)):
            assert "Not exported yet" in panel.get("description", ""), panel["title"]


def test_every_design_metric_has_a_panel() -> None:
    used = {metric_in(expr) for panel in PANELS for expr in exprs(panel)}
    assert set(DESIGN_ONLY) <= used


def test_panels_do_not_overlap() -> None:
    cells: set[tuple[int, int]] = set()
    for panel in DASHBOARD["panels"]:
        box = panel["gridPos"]
        area = {(x, y) for x in range(box["x"], box["x"] + box["w"]) for y in range(box["y"], box["y"] + box["h"])}
        assert not area & cells, panel["title"]
        cells |= area


@pytest.mark.skipif(not VORA_METRICS.exists(), reason=f"needs a Vora checkout: {VORA_METRICS} not found; set VORA_REPO")
def test_the_exported_list_matches_vora_source() -> None:
    registered = set(re.findall(r'Name:\s+"(vora_\w+)"', VORA_METRICS.read_text()))
    assert set(EXPORTED) <= registered, f"not in metrics.go: {set(EXPORTED) - registered}"
