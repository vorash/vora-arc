"""What a real run of the leak suites said, read from the files those runs wrote.

Nothing here measures a leak. A suite is "passed" only when its report names every test this
backend requires, each one passed, the run reached its end, and the report isn't older than the
bench sessions it stands next to. A suite with no report, or whose report names none of its
tests, is "not run".
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

RESET_TEST = "test_a_write_does_not_survive_into_the_next_run"
CONTROL_TEST = "test_without_a_reset_the_same_write_does_survive"
WRITER_CASES = ("write_workspace-0", "write_root_home-1", "fill_tmp-2")

RESET_SUITE = f"Pool reset: `{RESET_TEST}`"
CONTROL_SUITE = f"No-reset control: `{CONTROL_TEST}`"
VORA_SUITE = "Vora: leak matrices and disconnect"

BACKENDS = ("bwrap", "gvisor")
# TestPoolLeakMatrix and TestPoolDisconnectMidRun run once per backend as a subtest, and on a host
# that can't run a backend that row skips while the top-level test still passes.
VORA_TESTS: Mapping[str, tuple[str, ...]] = {
    "bwrap": ("TestBwrapReusableLeakMatrix", "TestPoolLeakMatrix/bwrap", "TestPoolDisconnectMidRun/bwrap"),
    "gvisor": ("TestLeakMatrixGvisor", "TestPoolLeakMatrix/gvisor", "TestPoolDisconnectMidRun/gvisor"),
}

FAILED = "FAILED"
NOT_RUN = "not run"
PASSED = "passed"
NOT_IN_REPORT = "not in the report"

_GO_RESULT = re.compile(r"^\s*--- (PASS|FAIL|SKIP): (\S+)", re.MULTILINE)
_GO_PANIC = re.compile(r"^panic:", re.MULTILINE)
_GO_FINISHED = re.compile(r"^(PASS|ok\s)")
_GO_FAILED = re.compile(r"^FAIL\b")
_VORA_BUILD = re.compile(r"^vora (?:commit|version):\s*(\S+)", re.MULTILINE)


@dataclass(frozen=True)
class LeakReport:
    backend: str
    path: Path


@dataclass(frozen=True)
class SuiteResult:
    suite: str
    backend: str
    expected: tuple[str, ...]
    passed: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    unfinished: bool = False
    """The report doesn't show its run reaching the end."""
    report: str | None = None
    written_at: datetime | None = None
    """The report's file time, or the date inside it if that is older: copying a file resets its time."""
    vora_build: str | None = None
    older_than_session: datetime | None = None
    """The start of a later bench session on this backend."""

    @property
    def missing(self) -> tuple[str, ...]:
        # Only a test's own line counts: a subtest's line says nothing about how its parent ended.
        seen = {*self.passed, *self.failed, *self.skipped}
        return tuple(test for test in self.expected if test not in seen)

    @property
    def incomplete(self) -> tuple[str, ...]:
        """Why the required tests don't add up to a pass, in words a reader can act on."""
        reasons = []
        if self.missing:
            reasons.append(f"missing {', '.join(self.missing)}")
        if self.skipped:
            reasons.append(f"skipped {', '.join(self.skipped)}")
        if self.unfinished:
            reasons.append("the log has no final PASS or ok line, so the run was cut off")
        return tuple(reasons)

    @property
    def status(self) -> str:
        if self.failed:
            return FAILED
        if self.report is None or (not self.passed and not self.skipped):
            return NOT_RUN
        if self.incomplete:
            return f"incomplete: {'; '.join(self.incomplete)}"
        if self.older_than_session is not None:
            return f"stale: older than the session started {_when(self.older_than_session)}"
        return PASSED

    @property
    def report_cell(self) -> str:
        if self.report is None:
            return "none given"
        written = _when(self.written_at) if self.written_at else "date unknown"
        return f"{self.report}, written {written}"


def read_leak_suites(
    pytest_reports: Sequence[LeakReport] = (),
    vora_reports: Sequence[LeakReport] = (),
    latest_session: Mapping[str, datetime] | None = None,
) -> tuple[SuiteResult, ...]:
    """One row per required suite and backend. ``latest_session`` is each benched backend's newest session start."""
    sessions = latest_session or {}
    backends = list(dict.fromkeys(sessions)) or list(BACKENDS)
    results: list[SuiteResult] = []
    for backend in dict.fromkeys([*backends, *(r.backend for r in (*pytest_reports, *vora_reports))]):
        results += [suite for report in pytest_reports if report.backend == backend for suite in _read_junit(report)]
        if backend in backends and not any(report.backend == backend for report in pytest_reports):
            results += [SuiteResult(suite, backend, expected) for suite, expected in _pytest_expected().items()]
        results += [_read_go_log(report) for report in vora_reports if report.backend == backend]
        if backend in backends and not any(report.backend == backend for report in vora_reports):
            results.append(SuiteResult(VORA_SUITE, backend, VORA_TESTS[backend]))
    return tuple(_flag_stale(suite, sessions.get(suite.backend)) for suite in results)


def _flag_stale(suite: SuiteResult, latest: datetime | None) -> SuiteResult:
    if latest is None or suite.written_at is None or suite.written_at >= latest:
        return suite
    return replace(suite, older_than_session=latest)


def _pytest_expected() -> dict[str, tuple[str, ...]]:
    return {
        RESET_SUITE: tuple(f"{RESET_TEST}[{case}]" for case in WRITER_CASES),
        CONTROL_SUITE: tuple(f"{CONTROL_TEST}[{case}]" for case in WRITER_CASES),
    }


def _read_junit(report: LeakReport) -> list[SuiteResult]:
    written = _file_time(report.path)
    try:
        root = ElementTree.parse(report.path).getroot()
    except (OSError, ElementTree.ParseError):
        root = None
    cases = list(root.iter("testcase")) if root is not None else []
    if root is not None:
        written = min(filter(None, [written, _junit_time(root)]), default=None)

    def tally(suite: str, expected: tuple[str, ...]) -> SuiteResult:
        results: dict[str, list[str]] = {"passed": [], "failed": [], "skipped": []}
        for case in cases:
            name = case.get("name") or ""
            if name not in expected:
                continue
            tags = {child.tag for child in case}
            results["failed" if tags & {"failure", "error"} else "skipped" if "skipped" in tags else "passed"].append(name)
        return SuiteResult(
            suite,
            report.backend,
            expected,
            tuple(results["passed"]),
            tuple(results["failed"]),
            tuple(results["skipped"]),
            report=str(report.path),
            written_at=written,
            vora_build=NOT_IN_REPORT,
        )

    return [tally(suite, expected) for suite, expected in _pytest_expected().items()]


def _read_go_log(report: LeakReport) -> SuiteResult:
    expected = VORA_TESTS[report.backend]
    written = _file_time(report.path)
    try:
        log = report.path.read_text(errors="replace")
    except OSError:
        return SuiteResult(VORA_SUITE, report.backend, expected, report=str(report.path))
    outcomes = {
        outcome: tuple(name for found, name in _GO_RESULT.findall(log) if found == outcome and _required(expected, name))
        for outcome in ("PASS", "FAIL", "SKIP")
    }
    lines = log.splitlines()
    last = next((line for line in reversed(lines) if line.strip()), "")
    # A panic or a failing package ends the binary without a --- line for what was running.
    ended_badly = bool(_GO_PANIC.search(log)) or bool(_GO_FAILED.match(last))
    build = _VORA_BUILD.search(log)
    return SuiteResult(
        VORA_SUITE,
        report.backend,
        expected,
        outcomes["PASS"],
        (*outcomes["FAIL"], *(("the log ended in a failure or panic",) if ended_badly else ())),
        outcomes["SKIP"],
        unfinished=not _GO_FINISHED.match(last),
        report=str(report.path),
        written_at=written,
        vora_build=build.group(1) if build else NOT_IN_REPORT,
    )


def _required(expected: Sequence[str], name: str) -> bool:
    return any(name == test or name.startswith(f"{test}/") for test in expected)


def _file_time(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        return None


def _junit_time(root: ElementTree.Element) -> datetime | None:
    for element in root.iter():
        stamp = element.get("timestamp")
        if stamp is None:
            continue
        try:
            return datetime.fromisoformat(stamp).astimezone(UTC)
        except ValueError:
            return None
    return None


def _when(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M UTC")
