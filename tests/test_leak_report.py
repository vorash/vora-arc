"""Leak results are read from what a real run wrote. Anything short of a pass must not read as one."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_hostile import WRITERS

from vora_arc.cli import main
from vora_arc.leak_report import (
    CONTROL_TEST,
    FAILED,
    NOT_RUN,
    PASSED,
    RESET_TEST,
    VORA_TESTS,
    WRITER_CASES,
    LeakReport,
    SuiteResult,
    read_leak_suites,
)

BWRAP_LOG = (
    "vora commit: abc123\n"
    "=== RUN   TestBwrapReusableLeakMatrix\n"
    "    --- PASS: TestBwrapReusableLeakMatrix/tmp (0.10s)\n"
    "--- PASS: TestBwrapReusableLeakMatrix (0.10s)\n"
    "--- SKIP: TestLeakMatrixGvisor (0.00s)\n"
    "        --- PASS: TestPoolLeakMatrix/bwrap/tmp/0 (0.10s)\n"
    "    --- PASS: TestPoolLeakMatrix/bwrap (1.00s)\n"
    "    --- SKIP: TestPoolLeakMatrix/gvisor (0.00s)\n"
    "--- PASS: TestPoolLeakMatrix (1.00s)\n"
    "    --- PASS: TestPoolDisconnectMidRun/bwrap (1.00s)\n"
    "    --- SKIP: TestPoolDisconnectMidRun/gvisor (0.00s)\n"
    "--- PASS: TestPoolDisconnectMidRun (1.00s)\n"
    "PASS\n"
    "ok  \tgithub.com/vorash/vora/tests/integration\t2.2s\n"
)
FRESH = datetime(2026, 1, 1, tzinfo=UTC)


def junit(path: Path, *cases: str) -> LeakReport:
    path.write_text(f"<testsuites><testsuite>{''.join(cases)}</testsuite></testsuites>")
    return LeakReport("bwrap", path)


def case(name: str, param: str = WRITER_CASES[0], child: str = "") -> str:
    return f'<testcase classname="tests.test_hostile" name="{name}[{param}]">{child}</testcase>'


def every_case(name: str) -> list[str]:
    return [case(name, param) for param in WRITER_CASES]


def go_log(path: Path, text: str = BWRAP_LOG, backend: str = "bwrap") -> LeakReport:
    path.write_text(text)
    return LeakReport(backend, path)


def vora_row(report: LeakReport) -> SuiteResult:
    return read_leak_suites(vora_reports=[report], latest_session={report.backend: FRESH})[-1]


def pool_rows(report: LeakReport) -> tuple[SuiteResult, ...]:
    return read_leak_suites([report], latest_session={report.backend: FRESH})[:2]


def test_the_expected_pytest_cases_are_the_ones_the_hostile_suite_runs() -> None:
    assert WRITER_CASES == tuple(f"{writer}-{cell}" for writer, cell in WRITERS.items())


def test_with_no_report_every_suite_of_a_benched_backend_is_not_run() -> None:
    rows = read_leak_suites(latest_session={"bwrap": FRESH})

    assert [(row.backend, row.status) for row in rows] == [("bwrap", NOT_RUN)] * 3
    assert rows[-1].missing == VORA_TESTS["bwrap"]


def test_with_nothing_benched_every_backend_is_not_run() -> None:
    assert {row.backend for row in read_leak_suites()} == {"bwrap", "gvisor"}
    assert {row.status for row in read_leak_suites()} == {NOT_RUN}


def test_a_pytest_report_is_read_per_test(tmp_path: Path) -> None:
    report = junit(tmp_path / "leak.xml", *every_case(RESET_TEST), *every_case(CONTROL_TEST), case("test_other"))

    reset, control = pool_rows(report)

    assert (reset.status, len(reset.passed), reset.report) == (PASSED, 3, str(report.path))
    assert control.status == PASSED


def test_one_case_of_three_is_incomplete_and_names_what_is_missing(tmp_path: Path) -> None:
    report = junit(tmp_path / "leak.xml", case(RESET_TEST, "fill_tmp-2"), case(CONTROL_TEST, "fill_tmp-2"))

    reset, control = pool_rows(report)

    for row in (reset, control):
        assert row.status.startswith("incomplete: missing"), row.status
        assert "[write_workspace-0]" in row.status and "[write_root_home-1]" in row.status
        assert "[fill_tmp-2]" not in row.status


def test_a_failed_leak_test_is_failed_and_an_error_counts_as_one(tmp_path: Path) -> None:
    report = junit(
        tmp_path / "leak.xml",
        case(RESET_TEST),
        case(RESET_TEST, "fill_tmp-2", "<failure/>"),
        case(CONTROL_TEST, child="<error/>"),
    )

    reset, control = pool_rows(report)

    assert (reset.status, len(reset.failed)) == (FAILED, 1)
    assert (control.status, len(control.failed)) == (FAILED, 1)


def test_a_skipped_control_is_not_a_pass(tmp_path: Path) -> None:
    # The control needs an admin key and a runner with the unsafe grant, and skips without them.
    report = junit(
        tmp_path / "leak.xml",
        *every_case(RESET_TEST),
        *[case(CONTROL_TEST, param, "<skipped/>") for param in WRITER_CASES],
    )

    reset, control = pool_rows(report)

    assert reset.status == PASSED
    assert control.status.startswith("incomplete: skipped"), control.status


def test_a_report_that_names_none_of_the_tests_or_cant_be_read_is_not_run(tmp_path: Path) -> None:
    unrelated = junit(tmp_path / "other.xml", case("test_something_else"))
    cut_short = tmp_path / "cut.xml"
    cut_short.write_text("<testsuites><testsu")

    for report in (unrelated, LeakReport("bwrap", cut_short), LeakReport("bwrap", tmp_path / "missing.xml")):
        assert [row.status for row in pool_rows(report)] == [NOT_RUN, NOT_RUN]


def test_a_finished_log_with_every_required_test_passes_and_shows_its_build(tmp_path: Path) -> None:
    row = vora_row(go_log(tmp_path / "vora.log"))

    assert row.status == PASSED
    assert row.vora_build == "abc123"
    assert row.written_at is not None


def test_another_backends_skips_dont_stop_this_backend_passing_but_its_own_do(tmp_path: Path) -> None:
    assert vora_row(go_log(tmp_path / "bwrap.log")).status == PASSED, "gVisor rows skip on a bwrap run"

    row = vora_row(go_log(tmp_path / "gvisor.log", backend="gvisor"))

    assert row.status.startswith("incomplete"), "the same log says nothing good about gVisor"
    assert "TestLeakMatrixGvisor" in row.status
    assert "TestPoolLeakMatrix/gvisor" in row.status


def test_a_skipped_row_under_a_required_test_is_incomplete_even_when_its_parent_passed(tmp_path: Path) -> None:
    text = BWRAP_LOG.replace("        --- PASS: TestPoolLeakMatrix/bwrap/tmp/0", "        --- SKIP: TestPoolLeakMatrix/bwrap/tmp/0")

    row = vora_row(go_log(tmp_path / "vora.log", text))

    assert row.status == "incomplete: skipped TestPoolLeakMatrix/bwrap/tmp/0"


def test_a_log_cut_off_mid_run_is_incomplete_and_names_what_never_finished(tmp_path: Path) -> None:
    text = (
        "=== RUN   TestBwrapReusableLeakMatrix\n"
        "    --- PASS: TestBwrapReusableLeakMatrix/tmp (0.10s)\n"
        "--- PASS: TestBwrapReusableLeakMatrix (0.10s)\n"
        "=== RUN   TestPoolLeakMatrix\n"
    )

    row = vora_row(go_log(tmp_path / "vora.log", text))

    assert row.status.startswith("incomplete"), row.status
    assert "TestPoolLeakMatrix/bwrap" in row.status and "no final PASS or ok line" in row.status


def test_every_required_line_without_a_final_line_is_still_not_a_pass(tmp_path: Path) -> None:
    text = BWRAP_LOG.split("PASS\nok")[0]

    row = vora_row(go_log(tmp_path / "vora.log", text))

    assert row.status == "incomplete: the log has no final PASS or ok line, so the run was cut off"


def test_a_log_with_only_the_bwrap_matrix_is_incomplete(tmp_path: Path) -> None:
    text = "--- PASS: TestBwrapReusableLeakMatrix (0.10s)\nPASS\nok  \tgithub.com/vorash/vora/tests/integration\t0.1s\n"

    row = vora_row(go_log(tmp_path / "vora.log", text))

    assert row.status == "incomplete: missing TestPoolLeakMatrix/bwrap, TestPoolDisconnectMidRun/bwrap"


def test_a_vora_log_that_panicked_or_ended_in_fail_is_failed_and_a_log_without_the_matrix_is_not_run(tmp_path: Path) -> None:
    panicked = go_log(tmp_path / "panicked.log", "--- PASS: TestBwrapReusableLeakMatrix (2.00s)\npanic: boom\n")
    ended = go_log(tmp_path / "ended.log", BWRAP_LOG.split("PASS\nok")[0] + "FAIL\nFAIL\tvora\t1.0s\n")
    silent = go_log(tmp_path / "silent.log", "ok  \tgithub.com/vorash/vora/tests/integration\t0.1s [no tests to run]\n")

    assert vora_row(panicked).status == FAILED
    assert vora_row(ended).status == FAILED
    assert vora_row(silent).status == NOT_RUN


def test_a_failed_required_subtest_is_failed(tmp_path: Path) -> None:
    text = BWRAP_LOG.replace("        --- PASS: TestPoolLeakMatrix/bwrap/tmp/0", "        --- FAIL: TestPoolLeakMatrix/bwrap/tmp/0")

    assert vora_row(go_log(tmp_path / "vora.log", text)).status == FAILED


def test_each_report_gets_its_own_row_under_its_backend(tmp_path: Path) -> None:
    bwrap = go_log(tmp_path / "bwrap.log")
    gvisor = go_log(tmp_path / "gvisor.log", "--- FAIL: TestLeakMatrixGvisor (1.00s)\n", "gvisor")

    rows = read_leak_suites(vora_reports=[bwrap, gvisor], latest_session={"bwrap": FRESH, "gvisor": FRESH})
    first, second = (row for row in rows if row.report)

    assert (first.backend, first.status, first.report) == ("bwrap", PASSED, str(bwrap.path))
    assert (second.backend, second.status, second.report) == ("gvisor", FAILED, str(gvisor.path))


def test_a_report_older_than_a_session_on_its_backend_is_stale_not_passed(tmp_path: Path) -> None:
    report = go_log(tmp_path / "vora.log")
    old = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    os.utime(report.path, (old, old))

    row = vora_row(report)

    assert row.status == f"stale: older than the session started {FRESH:%Y-%m-%d %H:%M} UTC"
    assert "2020-01-01" in row.report_cell


def test_a_date_inside_a_junit_report_counts_when_a_copy_reset_its_file_time(tmp_path: Path) -> None:
    path = tmp_path / "leak.xml"
    cases = "".join(every_case(RESET_TEST) + every_case(CONTROL_TEST))
    path.write_text(f'<testsuites><testsuite timestamp="2020-01-01T00:00:00+00:00">{cases}</testsuite></testsuites>')

    reset, _ = pool_rows(LeakReport("bwrap", path))

    assert reset.status.startswith("stale"), reset.status
    assert "2020-01-01" in reset.report_cell


def test_a_failed_suite_stays_failed_however_old(tmp_path: Path) -> None:
    report = go_log(tmp_path / "vora.log", "--- FAIL: TestPoolLeakMatrix/bwrap (1.00s)\nFAIL\n")
    os.utime(report.path, (0, 0))

    assert vora_row(report).status == FAILED


def test_the_cli_takes_each_report_with_its_backend(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["bench-summary", str(tmp_path / "raw.jsonl"), "--leak-vora", str(tmp_path / "vora.log")])
    with pytest.raises(SystemExit):
        main(["bench-summary", str(tmp_path / "raw.jsonl"), "--leak-pytest", f"firecracker={tmp_path / 'leak.xml'}"])


def _vora_tests() -> Path:
    return Path(os.environ.get("VORA_REPO", Path(__file__).resolve().parents[2] / "vora")) / "tests" / "integration"


@pytest.mark.skipif(
    not (_vora_tests() / "pool_leak_test.go").exists(),
    reason="needs a Vora checkout with vorash/vora#153, which isn't merged; set VORA_REPO to one",
)
def test_the_required_names_are_voras_own() -> None:
    source = "".join(path.read_text() for path in _vora_tests().glob("*_test.go"))
    tops = {test.split("/")[0] for tests in VORA_TESTS.values() for test in tests}
    for top in tops:
        assert f"func {top}(t *testing.T)" in source, top
    assert "poolHosts = []poolHost{bwrapPoolHost, gvisorPoolHost}" in source
    assert re.search(r'name:\s+"bwrap"', source) and re.search(r'name:\s+"gvisor"', source)
