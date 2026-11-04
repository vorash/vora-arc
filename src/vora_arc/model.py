from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

Grid = tuple[tuple[int, ...], ...]


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
    sandbox_id: str
    startup_ms: int
    exec_ms: int
    peak_mem_bytes: int | None
    cpu_ms: int | None
    stderr_tail: str


class Verdict(StrEnum):
    UNPARSEABLE = "unparseable"
    TIMEOUT = "timeout"
    CRASHED = "crashed"
    INVALID = "invalid"
    FAILED = "failed"
    MEMORIZED = "memorized"
    NONDETERMINISTIC = "nondeterministic"
    PASSED = "passed"
