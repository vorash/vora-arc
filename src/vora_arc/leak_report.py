"""What a real run of the leak suites said, read from the files those runs wrote.

Nothing here measures a leak. A suite with no report, or whose report names none of its tests,
is "not run", and a skipped test doesn't count as a pass.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

RESET_TEST = "test_a_write_does_not_survive_into_the_next_run"
CONTROL_TEST = "test_without_a_reset_the_same_write_does_survive"
VORA_MATRIX = "LeakMatrix"

RESET_SUITE = f"Pool reset: `{RESET_TEST}`"
CONTROL_SUITE = f"No-reset control: `{CONTROL_TEST}`"
VORA_SUITE = f"Vora: top-level tests named `*{VORA_MATRIX}*`"

_GO_RESULT = re.compile(r"^\s*--- (PASS|FAIL|SKIP): (\S+)", re.MULTILINE)
_GO_ABORT = re.compile(r"^(FAIL\b|panic:)", re.MULTILINE)


@dataclass(frozen=True)
class SuiteResult:
    suite: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    report: str | None = None

    @property
    def status(self) -> str:
        if self.failed:
            return "FAILED"
        if not self.passed:
            return "not run"
        return "incomplete: some tests skipped" if self.skipped else "passed"


def read_leak_suites(pytest_reports: Sequence[Path] = (), vora_reports: Sequence[Path] = ()) -> tuple[SuiteResult, ...]:
    pool = [suite for path in pytest_reports for suite in _read_junit(path)] or [
        SuiteResult(RESET_SUITE),
        SuiteResult(CONTROL_SUITE),
    ]
    vora = [_read_go_log(path) for path in vora_reports] or [SuiteResult(VORA_SUITE)]
    return (*pool, *vora)


def _read_junit(path: Path) -> tuple[SuiteResult, SuiteResult]:
    try:
        cases = list(ElementTree.parse(path).getroot().iter("testcase"))
    except (OSError, ElementTree.ParseError):
        cases = []

    def tally(suite: str, test: str) -> SuiteResult:
        passed = failed = skipped = 0
        for case in cases:
            if (case.get("name") or "").split("[")[0] != test:
                continue
            tags = {child.tag for child in case}
            if tags & {"failure", "error"}:
                failed += 1
            elif "skipped" in tags:
                skipped += 1
            else:
                passed += 1
        return SuiteResult(suite, passed, failed, skipped, str(path))

    return tally(RESET_SUITE, RESET_TEST), tally(CONTROL_SUITE, CONTROL_TEST)


def _read_go_log(path: Path) -> SuiteResult:
    try:
        log = path.read_text(errors="replace")
    except OSError:
        return SuiteResult(VORA_SUITE, report=str(path))
    results = [outcome for outcome, name in _GO_RESULT.findall(log) if VORA_MATRIX in name]
    # A panic ends the binary without a --- line for what was running.
    aborted = 1 if results and _GO_ABORT.search(log) else 0
    return SuiteResult(
        VORA_SUITE, results.count("PASS"), results.count("FAIL") + aborted, results.count("SKIP"), str(path)
    )
