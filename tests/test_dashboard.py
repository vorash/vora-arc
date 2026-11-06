"""The Grafana dashboard asks only for metrics Vora exports, with the labels they have."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = json.loads((ROOT / "dashboards" / "vora-arc.json").read_text())
PANELS = [panel for panel in DASHBOARD["panels"] if panel["type"] != "row"]
VORA = Path(os.environ.get("VORA_REPO", ROOT.parent / "vora"))
VORA_METRICS = VORA / "internal" / "telemetry" / "metrics.go"
VORA_RUNNER_POOLS = VORA / "internal" / "runner" / "pools.go"
VORA_POOL_MEMBER = VORA / "internal" / "pool" / "member.go"

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

# (metric, label) -> values, from internal/runner/pools.go and internal/pool/member.go. A test below compares them.
LABEL_VALUES: dict[tuple[str, str], set[str]] = {
    ("vora_pool_sandboxes", "state"): {"starting", "idle", "busy", "resetting", "retiring"},
    ("vora_pool_runs_total", "start"): {"warm", "cold"},
    ("vora_pool_run_duration_seconds", "start"): {"warm", "cold"},
    ("vora_pool_startup_seconds", "start"): {"warm", "cold"},
    ("vora_pool_reset_duration_seconds", "result"): {"ok", "failed"},
    ("vora_pool_retired_total", "cause"): {
        "max_runs", "max_age", "shrink", "idle_expiry", "reset_failed", "unhealthy", "drain", "expired",
    },
}  # fmt: skip


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


@dataclass(frozen=True)
class Query:
    """What one PromQL expression names. It covers only the PromQL these panels and their tests need."""

    metrics: tuple[str, ...]
    kept: frozenset[str]
    """`by` labels, which survive to a legend."""
    grouped: frozenset[str]
    """Every label in a `by`, `without`, `on`, `ignoring` or `group_*` clause."""
    matchers: tuple[tuple[str, str, str, str], ...]
    """Metric, label, operator and value of each selector matcher."""


FUNCTIONS = {"sum", "rate", "histogram_quantile", "avg", "min", "max", "count", "increase", "irate"}
_GROUPING = re.compile(r"\b(by|without|on|ignoring|group_left|group_right)\s*\(([^)]*)\)")
_SELECTOR = re.compile(r"([a-zA-Z_:][\w:]*)\s*(\{[^}]*\})?(?=\s*(\(|\[|\)|$|[-+*/,%^<>=!]|\b))")
_MATCHER = re.compile(r'(\w+)\s*(=~|!~|!=|=)\s*"([^"]*)"')


def parse(expr: str) -> Query:
    grouping = _GROUPING.findall(expr)
    rest = re.sub(r"\[[^\]]*\]", "", _GROUPING.sub(" ", expr))
    metrics: list[str] = []
    matchers: list[tuple[str, str, str, str]] = []
    for name, selector, after in _SELECTOR.findall(rest):
        if after == "(" and not selector:
            assert name in FUNCTIONS, f"{name} is not a function this reader knows, in {expr}"
            continue
        metrics.append(name)
        matchers += [(name, label, op, value) for label, op, value in _MATCHER.findall(selector)]
    labels = {keyword: _names(text) for keyword, text in grouping}
    return Query(
        metrics=tuple(metrics),
        kept=frozenset(labels.get("by", set())),
        grouped=frozenset(label for _, text in grouping for label in _names(text)),
        matchers=tuple(matchers),
    )


def _exported_name(metric: str) -> str:
    base = metric.removesuffix("_bucket")
    return base if "le" in EXPORTED.get(base, set()) else metric


def problems(expr: str) -> list[str]:
    """Why Prometheus would answer this expression with nothing, or with the wrong series."""
    query = parse(expr)
    found = [] if query.metrics else [f"no metric in {expr}"]
    for metric in query.metrics:
        name = _exported_name(metric)
        if name not in EXPORTED:
            found.append(f"{metric} is not exported by Vora")
            continue
        if (metric != name) != ("le" in EXPORTED[name]):
            found.append(f"{metric} is not read through its buckets")
        found += [f"{name} has no label {label}" for label in sorted(query.grouped - EXPORTED[name])]
    for metric, label, op, value in query.matchers:
        name = _exported_name(metric)
        if label not in EXPORTED.get(name, set()):
            found.append(f"{name} has no label {label}")
        known = LABEL_VALUES.get((name, label))
        if known is not None and op in ("=", "!="):
            wanted = {value}
        elif known is not None and re.fullmatch(r"\w+(\|\w+)*", value):
            wanted = set(value.split("|"))
        else:
            wanted = set()
        found += [f"{name} {label} is never {item}" for item in sorted(wanted - (known or set()))]
    return found


def exprs(panel: dict[str, Any]) -> list[str]:
    return [target["expr"] for target in panel["targets"]]


@pytest.mark.parametrize("panel", PANELS, ids=[panel["title"] for panel in PANELS])
def test_every_query_names_real_metrics_with_their_real_labels_and_values(panel: dict[str, Any]) -> None:
    for expr in exprs(panel):
        assert problems(expr) == []


@pytest.mark.parametrize(
    ("expr", "problem"),
    [
        ("sum by (pool, bogus) (vora_pool_sandboxes)", "no label bogus"),
        ("sum by(pool, bogus) (vora_pool_sandboxes)", "no label bogus"),
        ("sum without (bogus) (vora_pool_sandboxes)", "no label bogus"),
        ("sum(rate(vora_exec_total[1m])) / on (bogus) sum(rate(vora_exec_total[1m]))", "no label bogus"),
        ('sum(vora_pool_sandboxes{bogus="idle"})', "no label bogus"),
        ('sum(vora_pool_sandboxes{state="idel"})', "state is never idel"),
        ('sum(vora_pool_sandboxes{state!="idel"})', "state is never idel"),
        ('sum(vora_pool_sandboxes{state=~"idle|idel"})', "state is never idel"),
        ("sum(vora_pool_sandboxs)", "vora_pool_sandboxs is not exported"),
        ("sum(rate(vora_exec_total[1m])) / sum(rate(vora_no_such_metric[1m]))", "vora_no_such_metric is not exported"),
        ("sum(up)", "up is not exported"),
        ("histogram_quantile(0.5, sum by (le) (rate(vora_exec_duration_seconds[5m])))", "not read through its buckets"),
        ("sum(rate(vora_exec_total_bucket[5m]))", "vora_exec_total_bucket is not exported"),
    ],
)
def test_the_query_reader_catches_what_prometheus_would_silently_answer_with_nothing(expr: str, problem: str) -> None:
    assert any(problem in item for item in problems(expr)), problems(expr)


def test_a_valid_label_value_and_pattern_pass() -> None:
    assert problems('sum(vora_pool_sandboxes{state="idle"})') == []
    assert problems('sum(vora_pool_sandboxes{state=~"idle|busy"})') == []
    assert problems('sum(vora_pool_sandboxes{state=~"i.*"})') == [], "a real pattern can't be checked against a list"


@pytest.mark.parametrize("panel", PANELS, ids=[panel["title"] for panel in PANELS])
def test_a_legend_names_only_labels_its_query_kept(panel: dict[str, Any]) -> None:
    for target in panel["targets"]:
        used = set(re.findall(r"\{\{(\w+)\}\}", target.get("legendFormat", "")))
        query = parse(target["expr"])
        kept = query.kept | {label for _, label, _, _ in query.matchers}
        assert used <= kept, f"{target['legendFormat']} would be empty for {target['expr']}"


def test_the_four_spec_sections_exist() -> None:
    rows = [panel["title"] for panel in DASHBOARD["panels"] if panel["type"] == "row"]
    assert rows == ["Throughput", "Latency", "Pool state", "Policy events"]


def test_no_panel_still_says_its_metric_is_not_exported() -> None:
    for panel in PANELS:
        assert "Not exported" not in panel.get("description", ""), panel["title"]


def test_every_pool_metric_has_a_panel() -> None:
    used = {_exported_name(metric) for panel in PANELS for expr in exprs(panel) for metric in parse(expr).metrics}
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


@pytest.mark.skipif(not VORA_RUNNER_POOLS.exists(), reason=f"needs a Vora checkout: {VORA_RUNNER_POOLS} not found; set VORA_REPO")
def test_the_label_values_match_voras_source() -> None:
    runner = VORA_RUNNER_POOLS.read_text()
    states = re.search(r"States: map\[string\]int\{(.*?)\n\s*\},", runner, re.DOTALL)
    assert states is not None
    assert set(re.findall(r'"(\w+)":', states.group(1))) == LABEL_VALUES["vora_pool_sandboxes", "state"]
    assert set(re.findall(r'\bstart :?= "(\w+)"', runner)) == LABEL_VALUES["vora_pool_runs_total", "start"]
    results = re.findall(r'PoolResetDuration\.WithLabelValues\(label, "(\w+)"\)', runner)
    assert set(results) == LABEL_VALUES["vora_pool_reset_duration_seconds", "result"]
    causes = re.findall(r'Retire\w+\s+RetireCause = "(\w+)"', VORA_POOL_MEMBER.read_text())
    assert set(causes) == LABEL_VALUES["vora_pool_retired_total", "cause"]


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
