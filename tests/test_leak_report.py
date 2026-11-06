"""Leak results are read from what a real run wrote. Anything short of a pass must not read as one."""

from __future__ import annotations

from pathlib import Path

from vora_arc.leak_report import CONTROL_TEST, RESET_TEST, read_leak_suites


def junit(path: Path, *cases: str) -> Path:
    path.write_text(f"<testsuites><testsuite>{''.join(cases)}</testsuite></testsuites>")
    return path


def case(name: str, child: str = "") -> str:
    return f'<testcase classname="tests.test_hostile" name="{name}[write_workspace-0]">{child}</testcase>'


def test_with_no_report_every_suite_is_not_run() -> None:
    assert [suite.status for suite in read_leak_suites()] == ["not run", "not run", "not run"]


def test_a_pytest_report_is_read_per_test(tmp_path: Path) -> None:
    report = junit(tmp_path / "leak.xml", case(RESET_TEST), case(RESET_TEST), case(CONTROL_TEST), case("test_other"))

    reset, control, vora = read_leak_suites([report])

    assert (reset.status, reset.passed, reset.report) == ("passed", 2, str(report))
    assert (control.status, control.passed) == ("passed", 1)
    assert vora.status == "not run"


def test_a_failed_leak_test_is_failed_and_an_error_counts_as_one(tmp_path: Path) -> None:
    report = junit(
        tmp_path / "leak.xml",
        case(RESET_TEST),
        case(RESET_TEST, "<failure/>"),
        case(CONTROL_TEST, "<error/>"),
    )

    reset, control, _ = read_leak_suites([report])

    assert (reset.status, reset.failed) == ("FAILED", 1)
    assert (control.status, control.failed) == ("FAILED", 1)


def test_a_skipped_control_is_not_a_pass(tmp_path: Path) -> None:
    # The control needs an admin key and a runner with the unsafe grant, and skips without them.
    report = junit(tmp_path / "leak.xml", case(RESET_TEST), case(CONTROL_TEST, "<skipped/>"))

    reset, control, _ = read_leak_suites([report])

    assert reset.status == "passed"
    assert (control.status, control.skipped) == ("not run", 1)


def test_a_report_that_names_none_of_the_tests_or_cant_be_read_is_not_run(tmp_path: Path) -> None:
    unrelated = junit(tmp_path / "other.xml", case("test_something_else"))
    cut_short = tmp_path / "cut.xml"
    cut_short.write_text("<testsuites><testsu")

    for report in (unrelated, cut_short, tmp_path / "missing.xml"):
        assert [suite.status for suite in read_leak_suites([report])] == ["not run", "not run", "not run"]


def test_a_vora_log_passes_only_on_its_leak_matrix_lines(tmp_path: Path) -> None:
    log = tmp_path / "vora.log"
    log.write_text(
        "=== RUN   TestPoolLeakMatrix\n"
        "    --- PASS: TestPoolLeakMatrix/bwrap (1.00s)\n"
        "--- PASS: TestPoolLeakMatrix (1.00s)\n"
        "--- PASS: TestBwrapReusableLeakMatrix (2.00s)\n"
        "--- FAIL: TestSomethingElse (0.10s)\n"
    )

    *_, vora = read_leak_suites(vora_reports=[log])

    assert (vora.status, vora.passed, vora.failed) == ("passed", 3, 0)


def test_a_vora_log_with_skipped_subtests_is_incomplete(tmp_path: Path) -> None:
    # Vora's top-level matrix passes when its gVisor rows skip, which is what happens with no runsc.
    log = tmp_path / "vora.log"
    log.write_text("    --- SKIP: TestPoolLeakMatrix/gvisor (0.00s)\n    --- PASS: TestPoolLeakMatrix/bwrap (1.00s)\n--- PASS: TestPoolLeakMatrix (1.00s)\n")

    *_, vora = read_leak_suites(vora_reports=[log])

    assert (vora.status, vora.passed, vora.skipped) == ("incomplete: some tests skipped", 2, 1)


def test_a_vora_log_that_panicked_is_failed_and_a_log_without_the_matrix_is_not_run(tmp_path: Path) -> None:
    panicked = tmp_path / "panicked.log"
    panicked.write_text("--- PASS: TestBwrapReusableLeakMatrix (2.00s)\npanic: boom\n")
    silent = tmp_path / "silent.log"
    silent.write_text("ok  \tgithub.com/vorash/vora/tests/integration\t0.1s [no tests to run]\n")

    *_, broken = read_leak_suites(vora_reports=[panicked])
    *_, not_run = read_leak_suites(vora_reports=[silent])

    assert broken.status == "FAILED"
    assert not_run.status == "not run"


def test_each_backend_gets_its_own_row(tmp_path: Path) -> None:
    bwrap, gvisor = tmp_path / "bwrap.log", tmp_path / "gvisor.log"
    bwrap.write_text("--- PASS: TestPoolLeakMatrix (1.00s)\n")
    gvisor.write_text("--- FAIL: TestLeakMatrixGvisor (1.00s)\n")

    *_, first, second = read_leak_suites(vora_reports=[bwrap, gvisor])

    assert (first.status, first.report) == ("passed", str(bwrap))
    assert (second.status, second.report) == ("FAILED", str(gvisor))
