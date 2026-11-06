"""The raw file's rows, and the summary rebuilt from them. Nothing here talks to a server."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from .client import PoolMode
from .corpus import EXPENSIVE_CLASSES, CandidateClass
from .leak_report import FAILED, PASSED, SuiteResult, read_leak_suites
from .model import Verdict
from .report import DENIED_SYSCALLS_NOTE, NOT_MEASURED, blocked_net_note

UNSAFE_LABEL = "UNSAFE: no reset between runs, an experimental control only"
BUSY_LOAD_PER_CPU = 0.25
MIN_SESSIONS = 5
VORA_DEFAULT_MAX_AGE_S = 1800
CLIENT_CPU_WARN_SHARE = 0.5
RESET_FAILED = "POOL_RESET_FAILED"
UNDER_HALF_REPORTED = "under half reported"
IMAGE_UNCONFIRMED = "unconfirmed, and the cold arm may carry a registry attempt on every start (vorash/vora#148)"

_REQUIRED_WARM = {PoolMode.COLD: False, PoolMode.WARM: True, PoolMode.WARM_NO_RESET: True}
_REQUIRED_REUSE = {
    PoolMode.COLD: "POOL_REUSE_RESET",
    PoolMode.WARM: "POOL_REUSE_RESET",
    PoolMode.WARM_NO_RESET: "POOL_REUSE_UNSAFE_NO_RESET",
}

Phase = Literal["warmup", "measured"]


ORDINARY_ROW = f"Ordinary programs (all but {', '.join(sorted(EXPENSIVE_CLASSES))})"


def arm_label(arm: PoolMode) -> str:
    """The arm's name wherever it is shown, so the unsafe arm can't appear without its warning."""
    return f"{arm.value} ({UNSAFE_LABEL})" if arm is PoolMode.WARM_NO_RESET else arm.value


@dataclass(frozen=True)
class BenchHeader:
    session: str
    arm: str
    unsafe: bool
    started_at: str
    pool: str
    pool_shape: dict[str, Any]
    borrow_timeout_ms: int
    candidates: int
    warmup: int
    concurrency: int
    corpus_seed: int
    corpus_sha256: str
    corpus_mix: dict[str, int]
    """Parts of `corpus_denominator` per class, as configured."""
    corpus_denominator: int
    corpus_counts: dict[str, int]
    corpus_distinct_programs: dict[str, int]
    tasks_sha256: str
    profile: str
    backend: str
    image: str
    network: str
    cpu_millis: int
    memory_bytes: int
    pids: int
    api_url: str
    server_version: str | None
    server_version_source: str
    sdk_version: str | None
    sdk_rev: str | None
    git_commit: str | None
    git_dirty: bool | None
    hostname: str
    cpu_count: int | None
    load_start: tuple[float, float, float]
    image_resolved_via: str | None
    """What the operator checked on the host. A client can't read it: see docs/experiment-1.md."""


@dataclass(frozen=True)
class BenchRun:
    """One run, as the client saw it. A value Vora didn't report stays None, never 0."""

    session: str
    arm: str
    phase: Phase
    index: int
    candidate_class: str
    task: str
    program_sha256: str
    started_at: float
    wall_ms: float | None
    """Request sent to exit frame received, by the client's clock."""
    cycle_ms: float
    """Request sent to the end of the stream, which includes this run's reset."""
    client_startup_ms: float | None
    startup_ms: int | None
    """Vora's own figure: borrow wait, plus the cold start when cold."""
    exec_ms: float | None
    warm: bool | None
    """None when the run failed before its first frame."""
    reset_ms: int | None
    """This run's own reset."""
    prepared_reset_ms: int | None
    reset_outcome: str | None
    retire_cause: str | None
    reuse: str | None
    audit_log_id: str | None
    sandbox_id: str | None
    sandbox_run: int | None
    exit_reason: str | None
    exit_code: int | None
    output_sha256: str | None
    verdict: str | None
    """What the program earned. A junk program failing is a verdict. None only when the run has no result."""
    infra_failure: str | None
    """Vora failed, or the run has no result. It says nothing about the program."""
    failure_detail: str | None


@dataclass(frozen=True)
class BenchFooter:
    session: str
    ended_at: str
    completed: bool
    pool_ready_ms: float | None
    measured_seconds: float | None
    client_cpu_seconds: float | None
    """The measured window only: warmup and the pool's delete aren't what could limit the numbers."""
    load_end: tuple[float, float, float]


@dataclass(frozen=True)
class Percentiles:
    """Nearest-rank percentiles of what was reported. ``missing`` runs reported nothing."""

    count: int
    missing: int
    p50: float | None
    p90: float | None
    p99: float | None
    max: float | None


def percentiles(values: Iterable[float | None]) -> Percentiles:
    all_values = list(values)
    reported = sorted(value for value in all_values if value is not None)
    missing = len(all_values) - len(reported)
    if not reported:
        return Percentiles(0, missing, None, None, None, None)

    def rank(percent: int) -> float:
        return reported[max(math.ceil(percent / 100 * len(reported)) - 1, 0)]

    return Percentiles(len(reported), missing, rank(50), rank(90), rank(99), reported[-1])


@dataclass
class _ArmRows:
    header: BenchHeader
    runs: list[BenchRun] = field(default_factory=list)
    footer: BenchFooter | None = None


@dataclass(frozen=True)
class ClassSummary:
    name: str
    planned: int
    judged: int
    infra_failed: int
    verdicts: dict[str, int]
    wall: Percentiles
    slot_share: float | None
    """This class's share of the slot time the measured phase had: `concurrency` x its wall time."""


@dataclass(frozen=True)
class ArmSummary:
    header: BenchHeader
    footer: BenchFooter | None
    planned: int
    measured: int
    judged: int
    """Measured runs with a verdict. Only these count in the latencies and programs per second."""
    infra_failed: int
    infra_failures: dict[str, int]
    verdicts: dict[str, int]
    classes: tuple[ClassSummary, ...]
    hand_written_not_passed: tuple[int, ...]
    """Candidate indexes. A hand-written solution is known good, so this says the arm is broken."""
    warmup: int
    warmup_infra_failed: int
    warm: int
    cold: int
    started: int
    """Measured runs that got as far as a sandbox."""
    off_shape: int
    """Runs that started warm on the cold arm, or not warm on a warm arm."""
    off_shape_bound: int
    wrong_reuse: int
    reset_outcomes: dict[str, int]
    reset_failures: int
    retire_causes: dict[str, int]
    """What each run's check-in retired its member for. A member that retired while idle shows on no run."""
    sandboxes: int
    first_runs: int
    """Runs that were their sandbox's first. A healthy warm arm has one per member."""
    longest_sandbox_run: int | None
    wall: Percentiles
    ordinary: Percentiles
    """Wall-clock of every class but the expensive ones."""
    wall_values: tuple[float | None, ...]
    ordinary_values: tuple[float | None, ...]
    reset_values: tuple[int | None, ...]
    client_startup: Percentiles
    startup: Percentiles
    execution: Percentiles
    reset: Percentiles
    cycle: Percentiles
    programs_per_second: float | None

    @property
    def arm(self) -> PoolMode:
        return PoolMode(self.header.arm)

    @property
    def broken(self) -> bool:
        """On the no-reset arm a leak can legitimately fail a good program, which is a finding."""
        return bool(self.hand_written_not_passed) and self.arm is not PoolMode.WARM_NO_RESET

    @property
    def complete(self) -> bool:
        """A killed session or one with lost lines covers only part of its corpus, so its range means nothing."""
        return self.footer is not None and self.footer.completed and self.measured == self.planned

    @property
    def client_cpu_share(self) -> float | None:
        footer = self.footer
        if footer is None or footer.client_cpu_seconds is None or not footer.measured_seconds:
            return None
        return footer.client_cpu_seconds / footer.measured_seconds

    @property
    def off_shape_exceeded(self) -> bool:
        return self.off_shape > self.off_shape_bound

    @property
    def failed(self) -> bool:
        """What makes `bench` exit non-zero."""
        return bool(self.infra_failed or self.off_shape_exceeded or self.wrong_reuse or self.broken)


class Scope(StrEnum):
    """Who disagrees. Only `SAFE_ARMS` says an arm that must be right is wrong."""

    SAFE_ARMS = "arms that must agree"
    NO_RESET = "no-reset only"
    NO_RESET_UNCHECKED = "no-reset, with a safe arm's result missing"
    """Cold and warm can't both vouch for the other result, so this may not be the no-reset arm's doing."""


@dataclass(frozen=True)
class Disagreement:
    seed: int
    index: int
    candidate_class: str
    task: str
    program_sha256: str
    scope: Scope
    verdict_differs: bool
    output_differs: bool
    """Half the corpus is expected to fail, so a leak that changes a wrong answer shows only here."""
    verdicts: dict[str, dict[str, int]]
    """Arm to verdict to how many of that arm's sessions gave it."""
    outputs: dict[str, tuple[str, ...]]
    """Arm to the distinct output hashes its sessions gave."""


@dataclass(frozen=True)
class VerdictComparison:
    """One corpus, compared by candidate index across every session that ran it."""

    seed: int
    corpus_sha256: str
    arms: tuple[str, ...]
    compared: int
    """Candidates with a result from every arm that ran this corpus, at least two in all, and no failed run."""
    uncompared: int
    infra_failed: int
    """Candidates with an infrastructure failure in some session, all among `uncompared`."""
    disagreements: tuple[Disagreement, ...]


@dataclass(frozen=True)
class RawFile:
    arms: tuple[ArmSummary, ...]
    comparisons: tuple[VerdictComparison, ...]
    unreadable_lines: int


def load_raw(*paths: Path) -> RawFile:
    rows: dict[str, _ArmRows] = {}
    unreadable = 0
    for path in paths:
        for line in path.read_text().splitlines():
            try:
                raw = json.loads(line)
                kind = raw.pop("type")
                if kind == "header":
                    rows[raw["session"]] = _ArmRows(BenchHeader(**raw))
                elif kind == "run":
                    rows[raw["session"]].runs.append(BenchRun(**raw))
                elif kind == "footer":
                    rows[raw["session"]].footer = BenchFooter(**raw)
                else:
                    unreadable += 1
            except (ValueError, KeyError, TypeError, AttributeError):
                # The last line of a killed run can be cut short. The count shows in the summary.
                unreadable += 1
    sessions = list(rows.values())
    return RawFile(tuple(summarize(row) for row in sessions), compare_verdicts(sessions), unreadable)


def off_shape_bound(header: BenchHeader, footer: BenchFooter | None) -> int:
    """How many runs a healthy arm can start the wrong way. Above this, the arm really is off its shape.

    A cold arm has no warm members, so one warm run is wrong. A warm arm starts a run cold when a
    member retires: Vora's `Pool.remove` gives the freed slot to one waiter, as a cold start, if
    nothing else is in flight. So each retirement costs at most one cold run. A member retires
    only after `max_runs` runs, warmup counted, so 2,000 candidates after 24 warmup runs at
    `max_runs` 100 retire at most 2,024 // 100 = 20 members. `max_age` retires every member as
    well, which adds `concurrency` per elapsed `max_age` to a session long enough to reach it.
    """
    max_runs = int(header.pool_shape.get("max_runs", 0))
    if not max_runs:
        return 0
    measured_seconds = (footer.measured_seconds or 0.0) if footer else 0.0
    return (header.candidates + header.warmup) // max_runs + header.concurrency * int(measured_seconds // VORA_DEFAULT_MAX_AGE_S)


def summarize(rows: _ArmRows) -> ArmSummary:
    arm = PoolMode(rows.header.arm)
    measured = [run for run in rows.runs if run.phase == "measured"]
    warmup = [run for run in rows.runs if run.phase == "warmup"]
    judged = [run for run in measured if run.verdict is not None]
    framed = [run for run in measured if run.warm is not None]
    seconds = rows.footer.measured_seconds if rows.footer else None
    slot_ms = seconds * 1000 * rows.header.concurrency if seconds else None
    ordinary = [run for run in judged if run.candidate_class not in EXPENSIVE_CLASSES]
    return ArmSummary(
        header=rows.header,
        footer=rows.footer,
        planned=rows.header.candidates,
        measured=len(measured),
        judged=len(judged),
        infra_failed=sum(run.infra_failure is not None for run in measured),
        infra_failures=dict(Counter(run.infra_failure for run in measured if run.infra_failure is not None)),
        verdicts=dict(Counter(run.verdict for run in judged if run.verdict is not None)),
        classes=tuple(
            _class_summary(name, planned, [run for run in measured if run.candidate_class == name], slot_ms)
            for name, planned in rows.header.corpus_counts.items()
        ),
        hand_written_not_passed=tuple(
            sorted(
                run.index
                for run in judged
                if run.candidate_class == CandidateClass.HAND_WRITTEN and run.verdict != Verdict.PASSED
            )
        ),
        warmup=len(warmup),
        warmup_infra_failed=sum(run.infra_failure is not None for run in warmup),
        warm=sum(run.warm is True for run in framed),
        cold=sum(run.warm is False for run in framed),
        started=len(framed),
        off_shape=sum(run.warm is not _REQUIRED_WARM[arm] for run in framed),
        off_shape_bound=off_shape_bound(rows.header, rows.footer),
        wrong_reuse=sum((run.reuse or "POOL_REUSE_RESET") != _REQUIRED_REUSE[arm] for run in framed),
        reset_outcomes=dict(Counter(run.reset_outcome or "not reported" for run in framed)),
        reset_failures=sum(run.reset_outcome == RESET_FAILED for run in framed),
        retire_causes=dict(Counter(run.retire_cause for run in framed if run.retire_cause)),
        sandboxes=len({run.sandbox_id for run in framed if run.sandbox_id}),
        first_runs=sum(run.sandbox_run == 1 for run in framed),
        longest_sandbox_run=max((run.sandbox_run for run in framed if run.sandbox_run is not None), default=None),
        wall=percentiles(run.wall_ms for run in judged),
        ordinary=percentiles(run.wall_ms for run in ordinary),
        wall_values=tuple(run.wall_ms for run in judged),
        ordinary_values=tuple(run.wall_ms for run in ordinary),
        reset_values=tuple(run.reset_ms for run in judged),
        client_startup=percentiles(run.client_startup_ms for run in judged),
        startup=percentiles(run.startup_ms for run in judged),
        execution=percentiles(run.exec_ms for run in judged),
        reset=percentiles(run.reset_ms for run in judged),
        cycle=percentiles(run.cycle_ms for run in judged),
        programs_per_second=len(judged) / seconds if seconds else None,
    )


def _class_summary(name: str, planned: int, runs: Sequence[BenchRun], slot_ms: float | None) -> ClassSummary:
    judged = [run for run in runs if run.verdict is not None]
    return ClassSummary(
        name=name,
        planned=planned,
        judged=len(judged),
        infra_failed=sum(run.infra_failure is not None for run in runs),
        verdicts=dict(Counter(run.verdict for run in judged if run.verdict is not None)),
        wall=percentiles(run.wall_ms for run in judged),
        slot_share=sum(run.cycle_ms for run in runs) / slot_ms if slot_ms else None,
    )


@dataclass
class _Seen:
    seed: int
    candidate_class: str
    task: str
    program_sha256: str
    verdicts: dict[str, Counter[str]] = field(default_factory=dict)
    outputs: dict[str, set[str]] = field(default_factory=dict)
    results: int = 0
    infra_failed: bool = False

    def of_arms(self, arms: Iterable[str]) -> tuple[set[str], set[str]]:
        chosen = list(arms)
        verdicts = {verdict for arm in chosen for verdict in self.verdicts.get(arm, ())}
        outputs = {digest for arm in chosen for digest in self.outputs.get(arm, ())}
        return verdicts, outputs


def compare_verdicts(sessions: Iterable[_ArmRows]) -> tuple[VerdictComparison, ...]:
    """A run with no result has nothing to compare: it is counted as an infrastructure failure instead."""
    groups: dict[tuple[str, str], list[_ArmRows]] = {}
    for session in sessions:
        groups.setdefault((session.header.corpus_sha256, session.header.tasks_sha256), []).append(session)
    return tuple(_compare_corpus(group) for group in groups.values())


def _compare_corpus(sessions: Sequence[_ArmRows]) -> VerdictComparison:
    seed = sessions[0].header.corpus_seed
    arms = tuple(mode.value for mode in PoolMode if any(session.header.arm == mode for session in sessions))
    seen: dict[int, _Seen] = {}
    for session in sessions:
        arm = session.header.arm
        for run in session.runs:
            if run.phase != "measured":
                continue
            item = seen.setdefault(run.index, _Seen(seed, run.candidate_class, run.task, run.program_sha256))
            if run.verdict is None:
                item.infra_failed = True
                continue
            item.verdicts.setdefault(arm, Counter())[run.verdict] += 1
            item.results += 1
            if run.output_sha256 is not None:
                item.outputs.setdefault(arm, set()).add(run.output_sha256)
    compared = sum(_fully_compared(item, arms) for item in seen.values())
    found = (_disagreement(index, item) for index, item in sorted(seen.items()))
    return VerdictComparison(
        seed=seed,
        corpus_sha256=sessions[0].header.corpus_sha256,
        arms=arms,
        compared=compared,
        uncompared=len(seen) - compared,
        infra_failed=sum(item.infra_failed for item in seen.values()),
        disagreements=tuple(item for item in found if item is not None),
    )


def _fully_compared(item: _Seen, arms: Sequence[str]) -> bool:
    return item.results > 1 and not item.infra_failed and set(item.verdicts) == set(arms)


_SAFE_ARMS = (PoolMode.COLD.value, PoolMode.WARM.value)


def _disagreement(index: int, item: _Seen) -> Disagreement | None:
    verdicts, outputs = item.of_arms(item.verdicts)
    if len(verdicts) < 2 and len(outputs) < 2:
        return None
    safe_verdicts, safe_outputs = item.of_arms(_SAFE_ARMS)
    if len(safe_verdicts) > 1 or len(safe_outputs) > 1:
        scope = Scope.SAFE_ARMS
    elif all(arm in item.verdicts for arm in _SAFE_ARMS):
        scope = Scope.NO_RESET
    else:
        scope = Scope.NO_RESET_UNCHECKED
    return Disagreement(
        seed=item.seed,
        index=index,
        candidate_class=item.candidate_class,
        task=item.task,
        program_sha256=item.program_sha256,
        scope=scope,
        verdict_differs=len(verdicts) > 1,
        output_differs=len(outputs) > 1,
        verdicts={arm: dict(counts) for arm, counts in item.verdicts.items()},
        outputs={arm: tuple(sorted(digests)) for arm, digests in item.outputs.items()},
    )


def render_arm(summary: ArmSummary) -> str:
    header, footer = summary.header, summary.footer
    lines = [
        f"## {arm_label(summary.arm)}, session {header.session}",
        "",
        f"- Profile {header.profile}, backend {header.backend}, concurrency {header.concurrency}, shape {header.pool_shape}",
        f"- Corpus: {corpus_line(header)}",
        f"- Server version {header.server_version or NOT_MEASURED} ({header.server_version_source}), "
        f"SDK {header.sdk_version} at {header.sdk_rev}, git {header.git_commit}{' (dirty)' if header.git_dirty else ''}",
        f"- Host {header.hostname}, {header.cpu_count} CPUs, load {load_average(header.load_start)} at the start, "
        f"{load_average(footer.load_end) if footer else NOT_MEASURED} at the end, client CPU in the measured window "
        f"{f'{footer.client_cpu_seconds:.1f} s' if footer and footer.client_cpu_seconds is not None else NOT_MEASURED}",
        f"- Image resolved via: {header.image_resolved_via or IMAGE_UNCONFIRMED}",
        f"- Measured {summary.measured} of {summary.planned} planned: {summary.judged} with a verdict, "
        f"{summary.infra_failed} infrastructure failures" + (f" {summary.infra_failures}" if summary.infra_failures else ""),
        f"- Program verdicts: {summary.verdicts}",
        f"- Warmup, left out of everything below: {summary.warmup} runs, {summary.warmup_infra_failed} infrastructure failures",
        f"- Started warm {summary.warm}, cold {summary.cold}; not what this arm requires: {summary.off_shape} of "
        f"{summary.started}{_rate(summary.off_shape, summary.started)}, against a bound of {summary.off_shape_bound}; "
        f"wrong reuse mode: {summary.wrong_reuse}",
        f"- Reset outcomes: {summary.reset_outcomes}",
        f"- Retired at check-in: {summary.retire_causes}. {summary.sandboxes} sandboxes, {summary.first_runs} first runs, "
        f"longest sandbox {summary.longest_sandbox_run or NOT_MEASURED} runs",
        "- Programs per second: "
        + (
            NOT_MEASURED
            if summary.programs_per_second is None or footer is None or footer.measured_seconds is None
            else f"{summary.programs_per_second:.1f}, {summary.judged} verdicts over {footer.measured_seconds:.1f} s "
            f"of measured wall time at concurrency {header.concurrency}"
        ),
        f"- Denied syscalls: {NOT_MEASURED}. {DENIED_SYSCALLS_NOTE}",
        f"- Blocked network attempts: {blocked_net_note(header.network)}",
    ]
    if summary.hand_written_not_passed:
        lines.append(f"- **{_hand_written_warning(summary)}**")
    if summary.off_shape_exceeded:
        lines.append(f"- **{_off_shape_warning(summary)}**")
    if not summary.complete:
        lines.append("- **This arm did not finish. The numbers cover only what it logged.**")
    lines += [f"- **Warning: {warning}**" for warning in (*load_warnings(header), *client_cpu_warnings(summary))]
    lines += [
        "",
        "| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, values in (
        ("Wall-clock, start to exit (client)", summary.wall),
        ("Startup (Vora)", summary.startup),
        ("Startup (client)", summary.client_startup),
        ("Execution (client)", summary.execution),
        ("This run's reset (Vora)", summary.reset),
        ("Start to end of stream (client)", summary.cycle),
    ):
        lines.append(f"| {name} | {values.count} | {values.missing} | {_cells(values)} |")
    lines += [
        "",
        "Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of "
        "either covers only the slower runs it reported. A row with more left out than reported shows no percentile.",
        "",
        "| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max "
        "| Share of slot time | Verdicts |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| {ORDINARY_ROW} | | {summary.ordinary.count} | | {_cells(summary.ordinary)} | | |",
        f"| All classes | {summary.planned} | {summary.judged} | {summary.infra_failed} | {_cells(summary.wall)} "
        f"| {_share(_total_slot_share(summary))} | {summary.verdicts} |",
    ]
    lines += [
        f"| {row.name} | {row.planned} | {row.judged} | {row.infra_failed} | {_cells(row.wall)} "
        f"| {_share(row.slot_share)} | {row.verdicts} |"
        for row in summary.classes
    ]
    return "\n".join(lines) + "\n"


def _total_slot_share(summary: ArmSummary) -> float | None:
    shares = [row.slot_share for row in summary.classes]
    return None if any(share is None for share in shares) else sum(share for share in shares if share is not None)


def corpus_line(header: BenchHeader) -> str:
    parts = ", ".join(
        f"{name} {count} ({header.corpus_mix[name] * 100 / header.corpus_denominator:.2f}%, "
        f"{header.corpus_distinct_programs[name]} distinct)"
        for name, count in header.corpus_counts.items()
    )
    return f"seed {header.corpus_seed}, sha256 {header.corpus_sha256[:12]}, {parts}"


def _rate(count: int, total: int) -> str:
    return f" ({count * 100 / total:.1f}%)" if total else ""


def _off_shape_warning(summary: ArmSummary) -> str:
    return (
        f"{summary.arm.value} session {summary.header.session}: {summary.off_shape} runs started the wrong way, above the "
        f"bound of {summary.off_shape_bound} that retirements explain, so this arm is broken"
    )


def _hand_written_warning(summary: ArmSummary) -> str:
    count = len(summary.hand_written_not_passed)
    head = f"{summary.arm.value} session {summary.header.session}: {count} hand-written solutions did not pass"
    if summary.broken:
        return f"{head}. They are known good, so this arm is broken: candidates {list(summary.hand_written_not_passed)}"
    return f"{head}. On this unsafe arm that is a finding: state from an earlier run may have reached them: candidates {list(summary.hand_written_not_passed)}"


def render_summary(raw: RawFile, leak_suites: Sequence[SuiteResult] | None = None) -> str:
    lines = ["# Experiment 1 raw results", ""]
    if not raw.arms:
        lines.append("This file holds no complete header.")
    if raw.unreadable_lines:
        lines += [f"**{raw.unreadable_lines} lines of this file could not be read.**", ""]
    lines += _verdicts_section(raw)
    lines += _leak_section(read_leak_suites(latest_session=latest_session_by_backend(raw)) if leak_suites is None else leak_suites)
    lines += _comparison(raw.arms)
    lines += [render_arm(arm) for arm in raw.arms]
    return "\n".join(lines) + "\n"


def summary_exit_code(raw: RawFile, suites: Sequence[SuiteResult]) -> int:
    """1 when these results can't be trusted. A no-reset finding or a partial summary is still a useful answer."""
    safe_disagreement = any(item.scope is Scope.SAFE_ARMS for comparison in raw.comparisons for item in comparison.disagreements)
    broken_arm = any(arm.broken for arm in raw.arms)
    return 1 if safe_disagreement or broken_arm or any(suite.status == FAILED for suite in suites) else 0


def _verdicts_section(raw: RawFile) -> list[str]:
    if not raw.arms:
        return []
    disagreements = [item for comparison in raw.comparisons for item in comparison.disagreements]
    safe = [item for item in disagreements if item.scope is Scope.SAFE_ARMS]
    unsafe = [item for item in disagreements if item.scope is not Scope.SAFE_ARMS]
    compared = sum(comparison.compared for comparison in raw.comparisons)
    lines = ["## Verdicts and outputs across arms", ""]
    if safe:
        lines += [
            f"**{len(safe)} candidates differ on arms that must agree, in their verdict or their outputs. A program's "
            "result can't depend on how its sandbox started, so an arm is wrong. Don't quote these results until this "
            "is explained.**",
            "",
        ]
    if unsafe:
        lines += [
            f"**{len(unsafe)} candidates differ only where the unsafe no-reset arm is involved, in their verdict or their "
            "outputs. This is a finding, not an error: state from an earlier run may have reached them.**",
            "",
        ]
    lines += [f"**{_hand_written_warning(arm)}**\n" for arm in raw.arms if arm.hand_written_not_passed]
    if not disagreements:
        lines += [f"The {compared} candidates compared got the same verdict and outputs in every session that ran them.", ""]
    for comparison in raw.comparisons:
        lines += _comparison_notes(comparison)
    if safe:
        lines += ["", "On arms that must agree:", "", *_disagreement_table(safe)]
    if unsafe:
        lines += ["", "With the no-reset arm:", "", *_disagreement_table(unsafe)]
    return [*lines, ""]


def _disagreement_table(items: Sequence[Disagreement]) -> list[str]:
    columns = [mode.value for mode in PoolMode]
    lines = [
        f"| Seed | Candidate | Class | Task | Program | Differs on | Differs in | {' | '.join(columns)} |",
        f"|---|---|---|---|---|---|---|{'---|' * len(columns)}",
    ]
    lines += [
        f"| {item.seed} | {item.index} | {item.candidate_class} | {item.task} | {item.program_sha256[:12]} "
        f"| {item.scope.value} | {_differs_in(item)} | "
        + " | ".join(_arm_result(item, column) for column in columns)
        + " |"
        for item in items
    ]
    return lines


def _differs_in(item: Disagreement) -> str:
    parts = [name for name, differs in (("verdict", item.verdict_differs), ("outputs", item.output_differs)) if differs]
    return " and ".join(parts)


def _arm_result(item: Disagreement, arm: str) -> str:
    counts = item.verdicts.get(arm)
    if not counts:
        return "no verdict"
    verdicts = ", ".join(f"{verdict} x{count}" for verdict, count in sorted(counts.items()))
    return f"{verdicts}; outputs {', '.join(digest[:8] for digest in item.outputs.get(arm, ()))}"


def _comparison_notes(comparison: VerdictComparison) -> list[str]:
    notes = []
    if len(comparison.arms) < len(PoolMode):
        notes.append(f"Corpus seed {comparison.seed} ran only on {', '.join(comparison.arms)}.")
    if comparison.uncompared:
        notes.append(
            f"Corpus seed {comparison.seed}: {comparison.uncompared} candidates aren't compared, because a run has no result "
            f"or an arm has no verdict for them, {comparison.infra_failed} of them with an infrastructure failure."
        )
    return notes


def latest_session_by_backend(raw: RawFile) -> dict[str, datetime]:
    latest: dict[str, datetime] = {}
    for arm in raw.arms:
        started = datetime.fromisoformat(arm.header.started_at)
        latest[arm.header.backend] = max(started, latest.get(arm.header.backend, started))
    return latest


def _leak_section(suites: Sequence[SuiteResult]) -> list[str]:
    lines = ["## Leak tests", ""]
    short = [suite for suite in suites if suite.status != PASSED]
    if short:
        lines += [f"**{len(short)} of {len(suites)} leak suites did not pass. Nothing here shows the arms don't leak until each row says `passed`.**", ""]
    lines += [
        "| Suite | Backend | Result | Passed | Failed | Skipped | Report | Vora build |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {suite.suite} | {suite.backend} | {suite.status} | {len(suite.passed)} | {len(suite.failed)} | {len(suite.skipped)} "
        f"| {suite.report_cell} | {suite.vora_build or ''} |"
        for suite in suites
    ]
    return [*lines, ""]


def _comparison(arms: Sequence[ArmSummary]) -> list[str]:
    """Pooled figures and ranges cover complete sessions only. Failures count from every session."""
    if not arms:
        return []
    by_arm = [(mode, [arm for arm in arms if arm.arm is mode]) for mode in PoolMode]
    by_arm = [(mode, sessions) for mode, sessions in by_arm if sessions]
    lines = [
        "## Arms",
        "",
        f"Wall-clock in ms, start to exit, over complete sessions. Ordinary programs are every class but "
        f"{', '.join(sorted(EXPENSIVE_CLASSES))}.",
        "",
        *_wall_table(by_arm, lambda arm: arm.ordinary, lambda arm: arm.ordinary_values),
        "",
        "All classes. The expensive ones are under 1% of the runs, so when they are the slowest they fill most of the slowest 1%, "
        "and this p99 is then a near-worst run.",
        "",
        *_wall_table(by_arm, lambda arm: arm.wall, lambda arm: arm.wall_values),
        "",
        "| Arm | Reset p50, ms | Reset p99, ms | Resets reported | No figure from Vora | Reset failures | Programs/s (range) "
        "| Infrastructure failures | Off shape, against its bound | Hand-written not passed |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for mode, sessions in by_arm:
        complete = [arm for arm in sessions if arm.complete]
        reset = percentiles(value for arm in complete for value in arm.reset_values)
        failures = sum(arm.reset_failures for arm in sessions)
        lines.append(
            f"| {arm_label(mode)} | {_percentile_cell(reset, reset.p50)} | {_percentile_cell(reset, reset.p99)} "
            f"| {reset.count} | {reset.missing} | {f'**{failures}**' if failures else 0} "
            f"| {_median_range(arm.programs_per_second for arm in complete)} "
            f"| {sum(arm.infra_failed for arm in sessions)} of {sum(arm.measured for arm in sessions)} "
            f"| {_off_shape_cell(sessions)} "
            f"| {sum(len(arm.hand_written_not_passed) for arm in sessions)} |"
        )
    return [*lines, "", *_comparison_cautions(arms, by_arm), ""]


def _wall_table(
    by_arm: Sequence[tuple[PoolMode, Sequence[ArmSummary]]],
    per_session: Callable[[ArmSummary], Percentiles],
    values: Callable[[ArmSummary], Iterable[float | None]],
) -> list[str]:
    lines = [
        "| Arm | Sessions | Runs, pooled | p50 | p90 | p99 | Max | Per session: p50 median (range) | p99 median (range) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for mode, sessions in by_arm:
        complete = [arm for arm in sessions if arm.complete]
        pooled = percentiles(value for arm in complete for value in values(arm))
        lines.append(
            f"| {arm_label(mode)} | {_session_cell(len(complete), len(sessions) - len(complete))} | {pooled.count} | {_cells(pooled)} "
            f"| {_median_range(per_session(arm).p50 for arm in complete)} "
            f"| {_median_range(per_session(arm).p99 for arm in complete)} |"
        )
    return lines


def _session_cell(complete: int, incomplete: int) -> str:
    return f"{complete}, **plus {incomplete} incomplete**" if incomplete else str(complete)


def _off_shape_cell(sessions: Sequence[ArmSummary]) -> str:
    above = sum(arm.off_shape_exceeded for arm in sessions)
    cell = f"{sum(arm.off_shape for arm in sessions)}, bound {sum(arm.off_shape_bound for arm in sessions)}"
    return f"{cell}, **{above} sessions above theirs**" if above else cell


def _comparison_cautions(arms: Sequence[ArmSummary], by_arm: Sequence[tuple[PoolMode, Sequence[ArmSummary]]]) -> list[str]:
    notes = _p99_note(arms)
    incomplete = [arm for arm in arms if not arm.complete]
    if incomplete:
        listed = ", ".join(f"{arm.arm.value} {arm.header.session} ({arm.measured} of {arm.planned} measured)" for arm in incomplete)
        notes.append(f"**Incomplete sessions, left out of the pooled figures, ranges and session counts: {listed}.**")
    for mode, sessions in by_arm:
        complete = sum(arm.complete for arm in sessions)
        if complete < MIN_SESSIONS:
            notes.append(f"{mode.value} has {complete} complete sessions: fewer than {MIN_SESSIONS} can't show it reproduces.")
    if any(arm.header.image_resolved_via is None for arm in arms):
        notes.append(f"Image source: {IMAGE_UNCONFIRMED}.")
    corpora = {
        mode: frozenset((arm.header.corpus_sha256, arm.header.tasks_sha256) for arm in arms if arm.arm is mode)
        for mode in {arm.arm for arm in arms}
    }
    if len(set(corpora.values())) > 1:
        notes.append("These arms ran different corpora, so the arms are not comparable.")
    if len({(arm.header.concurrency, arm.header.backend) for arm in arms}) > 1:
        notes.append("These sessions differ in concurrency or backend, so the arms are not comparable.")
    notes += _session_differences(arms)
    notes += [warning for arm in arms for warning in client_cpu_warnings(arm)]
    order = sorted(arms, key=lambda arm: arm.header.started_at)
    notes.append(f"Session order: {', '.join(arm.header.arm for arm in order)}.")
    return notes


def _p99_note(arms: Sequence[ArmSummary]) -> list[str]:
    runs = [arm.ordinary.count for arm in arms if arm.complete and arm.ordinary.count]
    if not runs:
        return []
    smallest = min(runs)
    return [
        f"A session's p99 rests on its slowest 1%: about {max(round(smallest / 100), 1)} runs of the {smallest} ordinary runs "
        "in the smallest session here. Read the pooled p99 with the per-session range."
    ]


_SESSION_FACTS: Sequence[tuple[str, Callable[[BenchHeader], object]]] = (
    ("host", lambda header: header.hostname),
    ("commit", lambda header: header.git_commit),
    ("dirty state", lambda header: header.git_dirty),
    ("server version", lambda header: header.server_version),
    ("memory", lambda header: header.memory_bytes),
    ("warmup", lambda header: header.warmup),
)


def _session_differences(arms: Sequence[ArmSummary]) -> list[str]:
    """A raw file appends, so two hosts or two commits can sit in one file without anyone choosing that."""
    notes = []
    for name, fact in _SESSION_FACTS:
        values = {str(fact(arm.header)) for arm in arms}
        if len(values) > 1:
            notes.append(f"**These sessions differ in {name}: {', '.join(sorted(values))}.**")
    return notes


def _median_range(values: Iterable[float | None]) -> str:
    reported = [value for value in values if value is not None]
    if not reported:
        return NOT_MEASURED
    return f"{statistics.median(reported):.1f} ({min(reported):.1f} to {max(reported):.1f})"


def load_average(load: Sequence[float]) -> str:
    return " ".join(f"{value:.2f}" for value in load)


def _ms(value: float | None) -> str:
    return NOT_MEASURED if value is None else f"{value:.1f}"


def _percentile_cell(values: Percentiles, value: float | None) -> str:
    return UNDER_HALF_REPORTED if values.count and values.missing > values.count else _ms(value)


def _cells(values: Percentiles) -> str:
    return " | ".join(_percentile_cell(values, value) for value in (values.p50, values.p90, values.p99, values.max))


def _share(value: float | None) -> str:
    return NOT_MEASURED if value is None else f"{value * 100:.1f}%"


def client_cpu_warnings(summary: ArmSummary) -> list[str]:
    share = summary.client_cpu_share
    if share is None or share <= CLIENT_CPU_WARN_SHARE:
        return []
    return [
        f"{summary.arm.value} session {summary.header.session}: the client used {share * 100:.0f}% of a CPU over the measured "
        f"window, above the {CLIENT_CPU_WARN_SHARE * 100:.0f}% this summary allows. The client may be what limits this "
        "arm's throughput, not Vora"
    ]


def load_warnings(header: BenchHeader) -> list[str]:
    if header.cpu_count and header.load_start[0] > BUSY_LOAD_PER_CPU * header.cpu_count:
        return [f"this machine was busy at the start: load {header.load_start[0]} on {header.cpu_count} CPUs"]
    return []
