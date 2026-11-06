from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

Grid = tuple[tuple[int, ...], ...]

_URL_USERINFO = re.compile(r"(?<=://)[^/\s]*@")


@dataclass(frozen=True)
class Pair:
    input: Grid
    output: Grid


@dataclass(frozen=True)
class TestCase:
    __test__ = False  # not a pytest class, despite the name

    input: Grid
    output: Grid | None


@dataclass(frozen=True)
class Task:
    id: str
    train: tuple[Pair, ...]
    test: tuple[TestCase, ...]


class GridStatus(StrEnum):
    OK = "OK"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    INVALID = "INVALID"


class RunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    KILLED_TIMEOUT = "KILLED_TIMEOUT"
    KILLED_OOM = "KILLED_OOM"
    POLICY_VIOLATION = "POLICY_VIOLATION"


@dataclass(frozen=True)
class GridResult:
    index: int
    is_test: bool
    status: GridStatus
    output: Grid | None
    error: str | None
    wall_ms: int


@dataclass(frozen=True)
class BatchResult:
    correlation_id: str
    program_sha256: str
    run_status: RunStatus
    grids: tuple[GridResult, ...]
    sandbox_id: str | None
    startup_ms: int
    exec_ms: int
    peak_mem_bytes: int | None
    cpu_ms: int | None
    stderr_tail: str
    warm_start: bool = False
    reset_ms: int | None = None
    """This run's own reset, after it exited. None when none was reported, never 0 for that."""
    audit_log_id: str | None = None
    prepared_reset_ms: int | None = None
    """The earlier reset that prepared this run's sandbox."""
    reset_outcome: str | None = None
    sandbox_run: int | None = None


class Verdict(StrEnum):
    UNPARSEABLE = "unparseable"
    TIMEOUT = "timeout"
    CRASHED = "crashed"
    INVALID = "invalid"
    FAILED = "failed"
    MEMORIZED = "memorized"
    NONDETERMINISTIC = "nondeterministic"
    PASSED = "passed"


def storable_text(text: str) -> str:
    """Make untrusted text safe for PostgreSQL, which rejects NUL and lone surrogates."""
    return text.replace("\x00", "�").encode("utf-8", "replace").decode("utf-8")


def redact_userinfo(text: str) -> str:
    """Remove the credentials from any URL in `text`."""
    return _URL_USERINFO.sub("", text)
