"""`vora-arc bench` against fake pool routes, and its summary, which reads only the raw file."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fake_pools import ADMIN_KEY, TENANT_KEY, FakePools, Frames, Refuse, stdout_frame

from vora_arc import bench, cli
from vora_arc.bench import UNSAFE_LABEL, load_raw, percentiles, render_summary
from vora_arc.client import PoolMode

REVERSE = "def transform(grid):\n    return [row[::-1] for row in grid]\n"
TASK = {
    "train": [{"input": [[1, 2]], "output": [[2, 1]]}, {"input": [[3, 4]], "output": [[4, 3]]}],
    "test": [{"input": [[5, 6]], "output": [[6, 5]]}],
}
RIGHT = stdout_frame(
    {"index": 0, "status": "OK", "output": [[2, 1]], "error": None, "wall_ms": 1},
    {"index": 1, "status": "OK", "output": [[4, 3]], "error": None, "wall_ms": 1},
    {"index": 2, "status": "OK", "output": [[6, 5]], "error": None, "wall_ms": 1},
    {"done": True, "stderr_tail": ""},
)


@dataclass
class Bench:
    fake: FakePools
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "results" / "raw.jsonl"

    def run(self, mode: str, *extra: str) -> int:
        return cli.main(
            [
                "bench",
                "--mode",
                mode,
                "--task",
                "aaaa0001",
                "--program",
                str(self.root / "program.py"),
                "--data-dir",
                str(self.root / "data"),
                "--raw",
                str(self.raw),
                "--candidates",
                "6",
                "--warmup",
                "2",
                "--concurrency",
                "2",
                *extra,
            ]
        )

    def rows(self, kind: str) -> list[dict[str, Any]]:
        lines = [json.loads(line) for line in self.raw.read_text().splitlines()]
        return [line for line in lines if line["type"] == kind]


@pytest.fixture
def bencher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Bench]:
    split = tmp_path / "data" / "arc1" / "training"
    split.mkdir(parents=True)
    (split / "aaaa0001.json").write_text(json.dumps(TASK))
    (tmp_path / "program.py").write_text(REVERSE)
    monkeypatch.setattr(bench, "READY_POLL_S", 0.0)
    monkeypatch.delenv("VORA_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("VORA_ARC_TENANT_ID", raising=False)
    server = FakePools()
    with server.running():
        monkeypatch.setenv("VORA_API_URL", server.url)
        monkeypatch.setenv("VORA_API_KEY", TENANT_KEY)
        yield Bench(server, tmp_path)


def use_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORA_ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setenv("VORA_ARC_TENANT_ID", "tenant-a")


def test_the_three_arms_differ_only_in_pool_shape(bencher: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    use_admin(monkeypatch)
    for mode in PoolMode:
        assert bencher.run(mode.value) == 0

    runs = bencher.fake.calls("POST", "/run")
    assert len(runs) == 3 * (6 + 2)
    bodies = {json.dumps(call.body, sort_keys=True) for call in runs}
    assert len(bodies) == 1, "same program, same inputs, same timeout on every arm"
    assert bencher.fake.max_in_flight <= 2

    declared = [call.body for call in bencher.fake.calls("PUT")]
    shape_keys = {"name", "size", "maxSize", "maxRuns", "reuse", "tenantId"}
    rest = {json.dumps({k: v for k, v in body.items() if k not in shape_keys}, sort_keys=True) for body in declared if body}
    assert len(rest) == 1, "the sandbox and every limit are the same"
    headers = bencher.rows("header")
    assert {header["concurrency"] for header in headers} == {2}
    assert {header["program_sha256"] for header in headers} == {headers[0]["program_sha256"]}
    assert len(bencher.fake.calls("DELETE")) == 3, "every arm gives its pool back"


def test_the_raw_file_holds_every_run_and_enough_to_rebuild_a_report(bencher: Bench) -> None:
    assert bencher.run("warm", "--image-resolved-via", "containerd", "--server-version", "v0.10.9") == 0

    header = bencher.rows("header")[0]
    assert header["arm"] == "warm"
    assert header["server_version"] == "v0.10.9"
    assert header["sdk_version"] and header["sdk_rev"], "the pinned SDK says what it is"
    assert header["git_commit"]
    assert (header["backend"], header["profile"]) == ("gvisor", "python-arc")
    assert header["cpu_count"] and len(header["load_start"]) == 3
    assert (header["concurrency"], header["warmup"], header["candidates"]) == (2, 2, 6)
    assert header["image_resolved_via"] == "containerd"
    footer = bencher.rows("footer")[0]
    assert footer["completed"] is True
    assert len(footer["load_end"]) == 3
    assert footer["measured_seconds"] > 0

    runs = bencher.rows("run")
    assert [run["phase"] for run in runs].count("warmup") == 2
    assert [run["phase"] for run in runs].count("measured") == 6
    assert sorted(run["index"] for run in runs if run["phase"] == "measured") == list(range(6))
    run = runs[-1]
    assert run["arm"] == "warm"
    assert run["wall_ms"] > 0 and run["exec_ms"] >= 0 and run["cycle_ms"] >= run["wall_ms"]
    assert run["warm"] is True
    assert run["startup_ms"] == 1
    assert run["reset_ms"] == 3
    assert run["audit_log_id"].startswith("exe_")
    assert run["exit_reason"] == "EXITED"
    assert run["failure"] is None


def test_a_failed_run_is_counted_and_reported_never_dropped(bencher: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    bencher.fake.starting_polls = 0
    bencher.fake.runs.extend(
        [
            Frames(({"run": {"warm": True}}, RIGHT, {"exit": {"reason": "EXITED"}}, {"runDone": {}})),
            Frames(({"run": {"warm": True}}, RIGHT, {"exit": {"reason": "EXITED"}}, {"runDone": {}})),
            Refuse(429, "pool full"),
            Frames(({"run": {"warm": True, "sandboxId": "s"}}, {"error": {"code": "run_failed", "message": "gone"}})),
            Frames(({"run": {"warm": True}}, RIGHT, {"exit": {"reason": "RUNTIME_FAILURE"}}, {"runDone": {}})),
        ]
    )

    assert bencher.run("warm") == 1, "a bad run makes the command say so"

    summary = load_raw(bencher.raw).arms[0]
    assert summary.measured == 6
    assert summary.failed == 3
    assert summary.ok == 3
    assert summary.failures == {"RateLimitedError": 1, "run_failed": 1, "exit_reason:RUNTIME_FAILURE": 1}
    assert summary.wall.count == 3, "a refusal is fast, so it stays out of the latencies and shows in the count"
    assert "3 failed" in capsys.readouterr().out
    assert len(bencher.fake.calls("POST", "/run")) == 8, "a bench run is never retried"


def test_a_run_whose_program_gave_the_wrong_answer_is_a_failed_run(bencher: Bench) -> None:
    bencher.fake.transform = lambda grid: grid

    assert bencher.run("warm") == 1

    summary = load_raw(bencher.raw).arms[0]
    assert summary.ok == 0
    assert summary.failures == {"verdict:failed": 6}
    assert summary.wall.count == 0


def test_a_warm_arm_counts_a_run_that_was_not_warm(bencher: Bench) -> None:
    warm = Frames(({"run": {"warm": True}}, RIGHT, {"exit": {"reason": "EXITED"}}, {"runDone": {}}))
    cold = Frames(({"run": {"warm": False}}, RIGHT, {"exit": {"reason": "EXITED"}}, {"runDone": {}}))
    bencher.fake.runs.extend([warm, warm, cold, warm, warm, warm, warm, warm])

    assert bencher.run("warm") == 1

    summary = load_raw(bencher.raw).arms[0]
    assert (summary.warm, summary.cold, summary.off_shape) == (5, 1, 1)
    assert summary.failed == 0, "it ran fine, and stays in the latencies"
    assert summary.wall.count == 6


def test_the_cold_arm_counts_a_run_that_was_warm(bencher: Bench) -> None:
    warm = Frames(({"run": {"warm": True}}, RIGHT, {"exit": {"reason": "EXITED"}}, {"runDone": {}}))
    bencher.fake.runs.extend([warm] * 3)

    assert bencher.run("cold") == 1

    summary = load_raw(bencher.raw).arms[0]
    assert summary.off_shape == 1, "the first two went to warmup"
    assert summary.cold == 5


def test_a_warm_arm_that_got_an_unsafe_member_says_so(bencher: Bench) -> None:
    unsafe = {"run": {"warm": True, "reuse": "POOL_REUSE_UNSAFE_NO_RESET"}}
    bencher.fake.runs.extend([Frames((unsafe, RIGHT, {"exit": {"reason": "EXITED"}}, {"runDone": {}}))] * 3)

    assert bencher.run("warm") == 1

    assert load_raw(bencher.raw).arms[0].wrong_reuse == 1


def test_what_vora_left_out_is_null_in_the_raw_file_and_not_in_the_percentiles(bencher: Bench) -> None:
    assert bencher.run("cold") == 0

    runs = [run for run in bencher.rows("run") if run["phase"] == "measured"]
    assert {run["reset_ms"] for run in runs} == {None}, "a retired member had no reset, which isn't a reset of 0"
    summary = load_raw(bencher.raw).arms[0]
    assert (summary.reset.count, summary.reset.missing, summary.reset.p50) == (0, 6, None)
    assert "| This run's reset (Vora) | 0 | 6 | not measured | not measured | not measured | not measured |" in render_summary(
        load_raw(bencher.raw)
    )


def test_the_no_reset_arm_labels_itself_unsafe_everywhere_it_speaks(
    bencher: Bench, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_admin(monkeypatch)
    assert bencher.run("warm-no-reset") == 0

    printed = capsys.readouterr().out
    assert printed.splitlines()[0] == f"arm: warm-no-reset ({UNSAFE_LABEL})", "the first thing it says"
    assert f"## warm-no-reset ({UNSAFE_LABEL})" in printed
    assert bencher.rows("header")[0]["unsafe"] is True
    summary = render_summary(load_raw(bencher.raw))
    assert f"| warm-no-reset ({UNSAFE_LABEL}) |" in summary
    assert f"## warm-no-reset ({UNSAFE_LABEL})" in summary


def test_the_safe_arms_are_not_labelled_unsafe(bencher: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    assert bencher.run("warm") == 0
    assert bencher.run("cold") == 0

    assert "UNSAFE" not in capsys.readouterr().out
    assert "UNSAFE" not in render_summary(load_raw(bencher.raw))
    assert {header["unsafe"] for header in bencher.rows("header")} == {False}


def test_the_no_reset_arm_goes_through_the_admin_gate(bencher: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit, match="VORA_ADMIN_API_KEY"):
        bencher.run("warm-no-reset")
    assert bencher.fake.calls("PUT") == []
    assert bencher.rows("footer")[0]["completed"] is False, "the raw file says the arm didn't finish"

    use_admin(monkeypatch)
    assert bencher.run("warm-no-reset") == 0
    declare = bencher.fake.calls("PUT")[0]
    assert declare.key == ADMIN_KEY
    assert {call.key for call in bencher.fake.calls("POST", "/run")} == {TENANT_KEY}


def test_warm_runs_wait_for_the_pool_to_fill(bencher: Bench) -> None:
    bencher.fake.starting_polls = 3

    assert bencher.run("warm") == 0

    polled = bencher.fake.calls("GET", "/vora-arc-bench-warm-" + bencher.rows("header")[0]["session"])
    assert len(polled) == 3, "the declare's answer used up the first of the three"
    assert bencher.fake.seen.index(polled[-1]) < bencher.fake.seen.index(bencher.fake.calls("POST", "/run")[0])
    assert bencher.rows("footer")[0]["pool_ready_ms"] is not None


def test_a_pool_that_never_fills_ends_the_arm_and_gives_it_back(bencher: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench, "READY_TIMEOUT_S", 0.0)
    bencher.fake.starting_polls = 1000

    with pytest.raises(SystemExit, match="did not reach 2 idle"):
        bencher.run("warm")

    assert bencher.fake.calls("POST", "/run") == []
    assert len(bencher.fake.calls("DELETE")) == 1


def test_the_server_version_comes_from_the_admin_route_or_says_why_not(
    bencher: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert bencher.run("warm") == 0
    header = bencher.rows("header")[0]
    assert header["server_version"] is None
    assert "VORA_ADMIN_API_KEY" in header["server_version_source"]

    use_admin(monkeypatch)
    assert bencher.run("warm") == 0
    assert bencher.rows("header")[1]["server_version"] == "0.10.9"


def test_an_unconfirmed_image_source_is_said_out_loud(bencher: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    assert bencher.run("cold") == 0

    assert "image resolved via: unconfirmed" in capsys.readouterr().out
    assert "vorash/vora#148" in render_summary(load_raw(bencher.raw))


def test_a_busy_machine_is_said_out_loud(
    bencher: Bench, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(os, "getloadavg", lambda: (1000.0, 1000.0, 1000.0))

    assert bencher.run("cold") == 0

    assert "warning: this machine was busy" in capsys.readouterr().out
    assert "this machine was busy" in render_summary(load_raw(bencher.raw))


def test_a_summary_rebuilds_from_the_raw_file_with_no_server(bencher: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    assert bencher.run("warm") == 0
    live = capsys.readouterr().out
    bencher.fake.seen.clear()

    assert cli.main(["bench-summary", str(bencher.raw)]) == 0

    rebuilt = capsys.readouterr().out
    assert bencher.fake.seen == []
    section = rebuilt[rebuilt.index("## warm"):].strip()
    assert section in live, "the summary printed after a run is the one the file rebuilds"


def test_warmup_is_left_out_of_every_measured_number(bencher: Bench) -> None:
    assert bencher.run("warm") == 0
    lines = bencher.raw.read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    for row in rows:
        if row["type"] == "run" and row["phase"] == "warmup":
            row["wall_ms"] = 999999.0
    bencher.raw.write_text("".join(json.dumps(row) + "\n" for row in rows))

    summary = load_raw(bencher.raw).arms[0]
    assert summary.wall.max is not None and summary.wall.max < 999999.0
    assert (summary.warmup, summary.measured) == (2, 6)


def test_a_line_cut_short_by_a_kill_is_counted_and_the_rest_still_reads(bencher: Bench) -> None:
    assert bencher.run("warm") == 0
    with bencher.raw.open("a") as file:
        file.write('{"type": "run", "session": "abc')

    raw = load_raw(bencher.raw)

    assert raw.unreadable_lines == 1
    assert raw.arms[0].measured == 6
    assert "1 lines of this file could not be read" in render_summary(raw)


def test_an_arm_with_no_footer_says_it_did_not_finish(bencher: Bench) -> None:
    assert bencher.run("warm") == 0
    kept = [line for line in bencher.raw.read_text().splitlines() if json.loads(line)["type"] != "footer"]
    bencher.raw.write_text("\n".join(kept) + "\n")

    text = render_summary(load_raw(bencher.raw))

    assert "This arm did not finish" in text
    assert "Programs per second: not measured" in text


def test_sessions_of_an_arm_show_their_median_and_range_and_too_few_are_called_out(bencher: Bench) -> None:
    for _ in range(2):
        assert bencher.run("warm") == 0

    text = render_summary(load_raw(bencher.raw))

    assert "| warm | 2 | " in text
    assert "warm has 2 sessions: fewer than 5 can't show it reproduces." in text


def test_sessions_that_ran_different_things_are_not_compared_silently(bencher: Bench) -> None:
    assert bencher.run("warm") == 0
    (bencher.root / "program.py").write_text(REVERSE + "# another program\n")
    assert bencher.run("cold") == 0

    assert "so the arms are not comparable" in render_summary(load_raw(bencher.raw))


def test_denied_syscalls_and_blocked_network_never_read_as_zero(bencher: Bench) -> None:
    assert bencher.run("warm") == 0

    text = render_summary(load_raw(bencher.raw))

    assert "- Denied syscalls: not measured." in text
    assert "- Blocked network attempts: not measured: network mode none" in text
    assert "denied" not in json.dumps(bencher.rows("run")[0])


@pytest.mark.parametrize(
    ("values", "p50", "p90", "p99", "maximum"),
    [
        ([1.0], 1.0, 1.0, 1.0, 1.0),
        ([3.0, 1.0, 2.0, 4.0], 2.0, 4.0, 4.0, 4.0),
        ([float(n) for n in range(1, 101)], 50.0, 90.0, 99.0, 100.0),
    ],
)
def test_percentiles_are_nearest_rank(values: list[float], p50: float, p90: float, p99: float, maximum: float) -> None:
    result = percentiles(values)
    assert (result.count, result.p50, result.p90, result.p99, result.max) == (len(values), p50, p90, p99, maximum)


def test_a_percentile_ignores_what_was_not_reported_and_counts_it() -> None:
    result = percentiles([None, 10.0, None, 20.0])
    assert (result.count, result.missing, result.p50, result.max) == (2, 2, 10.0, 20.0)
    assert percentiles([None]).p50 is None
    assert percentiles([]).count == 0
