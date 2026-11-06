"""The Grafana dashboard asks only for metrics Vora exports, with the labels they have."""

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

# Metric -> labels, from internal/telemetry/metrics.go. A test below compares this with the source.
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
    "vora_pool_runs_total": {"pool", "start", "reason"},
    "vora_pool_run_duration_seconds": {"pool", "start", "le"},
    "vora_pool_startup_seconds": {"pool", "start", "le"},
    "vora_pool_reset_duration_seconds": {"pool", "result", "le"},
    "vora_pool_sandboxes": {"pool", "state"},
    "vora_pool_retired_total": {"pool", "cause"},
    "vora_pool_exhausted_total": {"pool"},
    "vora_pool_start_failed_total": {"pool"},
    "vora_pool_not_loaded": {"pool", "reason"},
    "vora_pool_events_dropped_total": set(),
}


def registered(source: str) -> dict[str, set[str]]:
    """Every metric metrics.go registers, with its labels: the Opts form and the NewDesc form."""
    metrics: dict[str, set[str]] = {}
    for block in re.split(r"(?=prometheus\.New(?:Counter|Gauge|Histogram)(?:Vec)?\()", source)[1:]:
        name = re.search(r'Name:\s+"(vora_\w+)"', block)
        if name is None:
            continue
        labels = re.search(r"\},\s*\[\]string\{([^}]*)\}\)", block)
        metrics[name.group(1)] = _names(labels.group(1)) if labels else set()
        if block.startswith("prometheus.NewHistogram"):
            metrics[name.group(1)].add("le")
    for name_text, labels_text in re.findall(r'prometheus\.NewDesc\("(vora_\w+)",\s*"[^"]*",\s*\[\]string\{([^}]*)\}', source):
        metrics[name_text] = _names(labels_text)
    return metrics


def _names(text: str) -> set[str]:
    return {item.strip().strip('"') for item in text.split(",") if item.strip()}


def metric_in(expr: str) -> str:
    match = re.search(r"\b(vora_\w+)", expr)
    assert match is not None, f"no Vora metric in {expr}"
    return match.group(1).removesuffix("_bucket")


def labels_in(expr: str) -> set[str]:
    grouped = {label.strip() for group in re.findall(r"by \(([^)]*)\)", expr) for label in group.split(",")}
    selected = {label for group in re.findall(r"\{([^}]*)\}", expr) for label in re.findall(r"(\w+)\s*[=!~]", group)}
    return grouped | selected


def exprs(panel: dict[str, Any]) -> list[str]:
    return [target["expr"] for target in panel["targets"]]


@pytest.mark.parametrize("panel", PANELS, ids=[panel["title"] for panel in PANELS])
def test_every_query_names_a_real_metric_with_its_real_labels(panel: dict[str, Any]) -> None:
    for expr in exprs(panel):
        metric = metric_in(expr)
        assert metric in EXPORTED, f"{metric} is not exported by Vora"
        assert labels_in(expr) <= EXPORTED[metric], f"{expr} uses a label {metric} doesn't have"


@pytest.mark.parametrize("panel", PANELS, ids=[panel["title"] for panel in PANELS])
def test_a_legend_names_only_labels_its_query_kept(panel: dict[str, Any]) -> None:
    for target in panel["targets"]:
        used = set(re.findall(r"\{\{(\w+)\}\}", target.get("legendFormat", "")))
        assert used <= labels_in(target["expr"]), f"{target['legendFormat']} would be empty for {target['expr']}"


@pytest.mark.parametrize("panel", PANELS, ids=[panel["title"] for panel in PANELS])
def test_a_histogram_is_read_through_its_buckets(panel: dict[str, Any]) -> None:
    for expr in exprs(panel):
        metric = metric_in(expr)
        assert ("_bucket" in expr) == ("le" in EXPORTED[metric]), expr


def test_the_four_spec_sections_exist() -> None:
    rows = [panel["title"] for panel in DASHBOARD["panels"] if panel["type"] == "row"]
    assert rows == ["Throughput", "Latency", "Pool state", "Policy events"]


def test_no_panel_still_says_its_metric_is_not_exported() -> None:
    for panel in PANELS:
        assert "Not exported" not in panel.get("description", ""), panel["title"]


def test_every_pool_metric_has_a_panel() -> None:
    used = {metric_in(expr) for panel in PANELS for expr in exprs(panel)}
    assert {metric for metric in EXPORTED if metric.startswith("vora_pool_")} <= used


def test_panels_do_not_overlap() -> None:
    cells: set[tuple[int, int]] = set()
    for panel in DASHBOARD["panels"]:
        box = panel["gridPos"]
        area = {(x, y) for x in range(box["x"], box["x"] + box["w"]) for y in range(box["y"], box["y"] + box["h"])}
        assert not area & cells, panel["title"]
        cells |= area


@pytest.mark.skipif(not VORA_METRICS.exists(), reason=f"needs a Vora checkout: {VORA_METRICS} not found; set VORA_REPO")
def test_the_exported_list_matches_vora_source() -> None:
    source = registered(VORA_METRICS.read_text())
    missing = set(EXPORTED) - set(source)
    assert not missing, f"not in metrics.go: {missing}"
    assert {name: source[name] for name in EXPORTED} == EXPORTED
    pools = {name for name in source if name.startswith("vora_pool_")}
    assert pools <= set(EXPORTED), f"Vora has pool metrics this list doesn't: {pools - set(EXPORTED)}"


def test_the_source_reader_sees_both_ways_metrics_go_declares_a_metric() -> None:
    source = """
    m.A = prometheus.NewCounterVec(prometheus.CounterOpts{
        Name: "vora_a_total",
    }, []string{"pool", "start"})
    m.B = prometheus.NewHistogramVec(prometheus.HistogramOpts{
        Name:    "vora_b_seconds",
        Buckets: []float64{0.1, 1},
    }, []string{"pool"})
    m.C = prometheus.NewCounter(prometheus.CounterOpts{
        Name: "vora_c_total",
    })
    m.D = prometheus.NewHistogram(prometheus.HistogramOpts{
        Name:    "vora_d_seconds",
        Buckets: prometheus.DefBuckets,
    })
    e = prometheus.NewDesc("vora_e", "Help, with a comma.", []string{"pool", "state"}, nil)
    """
    assert registered(source) == {
        "vora_a_total": {"pool", "start"},
        "vora_b_seconds": {"pool", "le"},
        "vora_c_total": set(),
        "vora_d_seconds": {"le"},
        "vora_e": {"pool", "state"},
    }
