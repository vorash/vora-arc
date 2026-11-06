"""`vora-arc bench`: one arm of experiment 1, and a summary rebuilt from its raw file.

The three arms run the same program on the same task inputs at the same concurrency,
and differ only in pool shape (`client.pool_shape`). Every number in a summary comes
from the raw file. See docs/experiment-1.md for what limits each arm's number.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import math
import os
import platform
import secrets
import statistics
import subprocess
import time
from collections import Counter
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Literal, TextIO

import httpx
from vora import Pool, Vora, VoraError

from .client import (
    PoolMode,
    PoolRunRecord,
    SandboxInfrastructureError,
    batch_request,
    open_pool,
    pool_result,
    pool_shape,
    run_in_pool,
)
from .model import Task, Verdict, redact_userinfo
from .profile import Profile
from .report import DENIED_SYSCALLS_NOTE, NOT_MEASURED, blocked_net_note
from .verify import verify

ROOT = Path(__file__).resolve().parents[2]
ADMIN_KEY_ENV = "VORA_ADMIN_API_KEY"
TENANT_ENV = "VORA_ARC_TENANT_ID"

UNSAFE_LABEL = "UNSAFE: no reset between runs, an experimental control only"
# Long enough that a slow replacement member shows as a slow run, not as a refusal.
# The same on every arm, because it isn't part of a pool's shape.
BORROW_TIMEOUT_MS = 60_000
READY_TIMEOUT_S = 120.0
READY_POLL_S = 0.1
READ_VERSION_TIMEOUT_S = 30.0
BUSY_LOAD_PER_CPU = 0.25
MIN_SESSIONS = 5
MAX_DETAIL_CHARS = 500
_IMAGE_UNCONFIRMED = "unconfirmed, and the cold arm may carry a registry attempt on every start (vorash/vora#148)"

_REQUIRED_WARM = {PoolMode.COLD: False, PoolMode.WARM: True, PoolMode.WARM_NO_RESET: True}
_REQUIRED_REUSE = {
    PoolMode.COLD: "POOL_REUSE_RESET",
    PoolMode.WARM: "POOL_REUSE_RESET",
    PoolMode.WARM_NO_RESET: "POOL_REUSE_UNSAFE_NO_RESET",
}

Phase = Literal["warmup", "measured"]


def arm_label(arm: PoolMode) -> str:
    """The arm's name wherever it is shown, so the unsafe arm can't appear without its warning."""
    return f"{arm.value} ({UNSAFE_LABEL})" if arm is PoolMode.WARM_NO_RESET else arm.value


@dataclass(frozen=True)
class BenchSettings:
    arm: PoolMode
    candidates: int
    warmup: int
    concurrency: int
    image_resolved_via: str | None
    server_version: str | None


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
    task: str
    inputs: int
    program_sha256: str
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
    failure: str | None
    """None when the run exited cleanly and the program passed. Otherwise what went wrong."""
    failure_detail: str | None


@dataclass(frozen=True)
class BenchFooter:
    session: str
    ended_at: str
    completed: bool
    pool_ready_ms: float | None
    measured_seconds: float | None
    client_cpu_seconds: float
    load_end: tuple[float, float, float]


class RawLog:
    """The append-only raw file. Each line reaches the OS as it is written, so a killed
    run keeps what it measured."""

    def __init__(self, file: TextIO) -> None:
        self._file = file

    def write(self, kind: str, row: Any) -> None:
        self._file.write(json.dumps({"type": kind} | asdict(row)) + "\n")
        self._file.flush()


@dataclass(frozen=True)
class _Job:
    pool: Pool
    profile: Profile
    task: Task
    program: str
    stdin: str
    is_test: tuple[bool, ...]
    settings: BenchSettings
    session: str
    log: RawLog


async def run_bench(
    profile: Profile, task: Task, program: str, settings: BenchSettings, raw_path: Path, *, vora: Vora
) -> int:
    """Run one arm and append it to ``raw_path``. Non-zero if any measured run went wrong."""
    session = secrets.token_hex(3)
    pool_name = f"vora-arc-bench-{settings.arm.value}-{session}"
    tenant_id = os.environ.get(TENANT_ENV) or None
    async with _admin_client() as admin:
        version, version_source = await _server_version(settings.server_version)
        header = _header(profile, task, program, settings, session, pool_name, version, version_source)
        _print_preflight(header)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with raw_path.open("a") as file:
            log = RawLog(file)
            log.write("header", header)
            cpu_started = _cpu_seconds()
            ready_ms: float | None = None
            measured_seconds: float | None = None
            completed = False
            try:
                async with open_pool(
                    vora,
                    profile,
                    pool_name,
                    settings.arm,
                    settings.concurrency,
                    admin=admin,
                    tenant_id=tenant_id,
                    borrow_timeout_ms=BORROW_TIMEOUT_MS,
                ) as pool:
                    stdin, is_test = batch_request(profile, program, task)
                    job = _Job(pool, profile, task, program, stdin, is_test, settings, session, log)
                    ready_ms = await _wait_until_ready(pool, settings)
                    await _run_phase(job, "warmup", settings.warmup)
                    started = time.perf_counter()
                    await _run_phase(job, "measured", settings.candidates)
                    measured_seconds = time.perf_counter() - started
                    completed = True
            finally:
                log.write(
                    "footer",
                    BenchFooter(
                        session,
                        datetime.now(UTC).isoformat(),
                        completed,
                        ready_ms,
                        measured_seconds,
                        _cpu_seconds() - cpu_started,
                        os.getloadavg(),
                    ),
                )
    summary = next(arm for arm in load_raw(raw_path).arms if arm.header.session == session)
    print(render_arm(summary))
    return 1 if summary.failed or summary.off_shape or summary.wrong_reuse else 0


@contextlib.asynccontextmanager
async def _admin_client() -> AsyncIterator[Vora | None]:
    key = os.environ.get(ADMIN_KEY_ENV)
    if not key:
        yield None
        return
    async with Vora(api_key=key) as admin:
        yield admin


async def _server_version(given: str | None) -> tuple[str | None, str]:
    if given is not None:
        return given, "--server-version"
    key = os.environ.get(ADMIN_KEY_ENV)
    if not key:
        return None, f"not read: GET /v1/runners needs {ADMIN_KEY_ENV}, a global admin's key"
    url = os.environ.get("VORA_API_URL", "http://127.0.0.1:9300").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=READ_VERSION_TIMEOUT_S) as http:
            response = await http.get(f"{url}/v1/runners", headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
    except httpx.HTTPError as error:
        return None, f"not read: GET /v1/runners answered: {error}"
    versions = sorted({str(runner.get("version")) for runner in response.json().get("runners") or []})
    return ",".join(versions) or None, "GET /v1/runners"


def _header(
    profile: Profile,
    task: Task,
    program: str,
    settings: BenchSettings,
    session: str,
    pool_name: str,
    version: str | None,
    version_source: str,
) -> BenchHeader:
    commit, dirty = _git_state()
    sdk_version, sdk_rev = _sdk_state()
    return BenchHeader(
        session=session,
        arm=settings.arm.value,
        unsafe=settings.arm is PoolMode.WARM_NO_RESET,
        started_at=datetime.now(UTC).isoformat(),
        pool=pool_name,
        pool_shape=pool_shape(settings.arm, settings.concurrency),
        borrow_timeout_ms=BORROW_TIMEOUT_MS,
        candidates=settings.candidates,
        warmup=settings.warmup,
        concurrency=settings.concurrency,
        task=task.id,
        inputs=len(task.train) + len(task.test),
        program_sha256=hashlib.sha256(program.encode()).hexdigest(),
        profile=profile.name,
        backend=profile.backend,
        image=profile.image,
        network=profile.network,
        cpu_millis=profile.cpu_millis,
        memory_bytes=profile.memory_bytes,
        pids=profile.pids,
        api_url=redact_userinfo(os.environ.get("VORA_API_URL", "")),
        server_version=version,
        server_version_source=version_source,
        sdk_version=sdk_version,
        sdk_rev=sdk_rev,
        git_commit=commit,
        git_dirty=dirty,
        hostname=platform.node(),
        cpu_count=os.cpu_count(),
        load_start=os.getloadavg(),
        image_resolved_via=settings.image_resolved_via,
    )


def _git_state() -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None, None
    return commit.stdout.strip(), bool(status.stdout.strip())


def _sdk_state() -> tuple[str | None, str | None]:
    try:
        distribution = metadata.distribution("vorash")
    except metadata.PackageNotFoundError:
        return None, None
    direct_url = distribution.read_text("direct_url.json")
    revision = json.loads(direct_url).get("vcs_info", {}).get("commit_id") if direct_url else None
    return distribution.version, revision


def _print_preflight(header: BenchHeader) -> None:
    arm = PoolMode(header.arm)
    print(f"arm: {arm_label(arm)}")
    print(f"session {header.session}, pool {header.pool}, shape {header.pool_shape}")
    print(f"profile {header.profile}, backend {header.backend}, image {header.image}, network {header.network}")
    print(f"program {header.program_sha256[:12]} on task {header.task} ({header.inputs} inputs)")
    print(f"{header.candidates} measured runs after {header.warmup} warmup runs, at concurrency {header.concurrency}")
    print(f"server version: {header.server_version or NOT_MEASURED} ({header.server_version_source})")
    print(f"sdk: {header.sdk_version} at {header.sdk_rev}; git: {header.git_commit}{' (dirty)' if header.git_dirty else ''}")
    print(f"load average on {header.hostname}: {_load(header.load_start)}, {header.cpu_count} CPUs")
    print(f"image resolved via: {header.image_resolved_via or _IMAGE_UNCONFIRMED}")
    for warning in _load_warnings(header):
        print(f"warning: {warning}")


def _load_warnings(header: BenchHeader) -> list[str]:
    if header.cpu_count and header.load_start[0] > BUSY_LOAD_PER_CPU * header.cpu_count:
        return [f"this machine was busy at the start: load {header.load_start[0]} on {header.cpu_count} CPUs"]
    return []


async def _wait_until_ready(pool: Pool, settings: BenchSettings) -> float:
    """Declare returns while members start, and a run in that gap isn't a warm run's cost."""
    size = pool_shape(settings.arm, settings.concurrency)["size"]
    started = time.perf_counter()
    while size:
        stats = await pool.stats()
        if stats is not None and stats.idle >= size:
            break
        if time.perf_counter() - started > READY_TIMEOUT_S:
            detail = stats.last_start_error if stats is not None else f"state {pool.info.state}"
            raise SystemExit(f"pool {pool.name} did not reach {size} idle members in {READY_TIMEOUT_S} s: {detail}")
        await asyncio.sleep(READY_POLL_S)
    return (time.perf_counter() - started) * 1000


async def _run_phase(job: _Job, phase: Phase, count: int) -> None:
    indexes = iter(range(count))

    async def worker() -> None:
        for index in indexes:
            job.log.write("run", await _one_run(job, phase, index))

    async with asyncio.TaskGroup() as group:
        for _ in range(job.settings.concurrency):
            group.create_task(worker())


async def _one_run(job: _Job, phase: Phase, index: int) -> BenchRun:
    started_at = time.time()
    began = time.perf_counter()
    correlation_id = f"bench/{job.session}/{phase}/{index}"
    try:
        record = await run_in_pool(job.pool, job.profile, job.stdin, job.is_test)
    except VoraError as error:
        return _refused(job, phase, index, started_at, (time.perf_counter() - began) * 1000, error)
    failure, detail, digest = await _judge(job, correlation_id, record)
    return _measured(job, phase, index, started_at, record, failure, detail, digest)


async def _judge(job: _Job, correlation_id: str, record: PoolRunRecord) -> tuple[str | None, str | None, str | None]:
    """A fast failure would flatter any arm, so a run only counts if the program really passed."""
    try:
        result = await pool_result(job.pool, job.profile, job.program, job.is_test, correlation_id, record)
    except SandboxInfrastructureError as error:
        code = record.failure.code if record.failure else f"exit_reason:{record.exit.reason if record.exit else None}"
        return code, str(error)[:MAX_DETAIL_CHARS], None
    outcome = verify(job.task, job.program, result)
    outputs = json.dumps([[grid.index, grid.status, grid.output] for grid in result.grids])
    digest = hashlib.sha256(outputs.encode()).hexdigest()
    if outcome.verdict is not Verdict.PASSED:
        return f"verdict:{outcome.verdict}", result.stderr_tail[-MAX_DETAIL_CHARS:] or None, digest
    return None, None, digest


def _refused(job: _Job, phase: Phase, index: int, started_at: float, cycle_ms: float, error: VoraError) -> BenchRun:
    return BenchRun(
        session=job.session,
        arm=job.settings.arm.value,
        phase=phase,
        index=index,
        started_at=started_at,
        wall_ms=None,
        cycle_ms=cycle_ms,
        client_startup_ms=None,
        startup_ms=None,
        exec_ms=None,
        warm=None,
        reset_ms=None,
        prepared_reset_ms=None,
        reset_outcome=None,
        retire_cause=None,
        reuse=None,
        audit_log_id=None,
        sandbox_id=None,
        sandbox_run=None,
        exit_reason=None,
        exit_code=None,
        output_sha256=None,
        failure=type(error).__name__,
        failure_detail=str(error)[:MAX_DETAIL_CHARS],
    )


def _measured(
    job: _Job,
    phase: Phase,
    index: int,
    started_at: float,
    record: PoolRunRecord,
    failure: str | None,
    detail: str | None,
    digest: str | None,
) -> BenchRun:
    run, exit_, done = record.run, record.exit, record.done
    return BenchRun(
        session=job.session,
        arm=job.settings.arm.value,
        phase=phase,
        index=index,
        started_at=started_at,
        wall_ms=record.wall_ms,
        cycle_ms=record.cycle_ms,
        client_startup_ms=record.startup_ms,
        startup_ms=run.startup_ms if run else None,
        exec_ms=record.exec_ms,
        warm=run.warm if run else None,
        reset_ms=done.reset_ms if done else None,
        prepared_reset_ms=run.reset_ms if run else None,
        reset_outcome=done.outcome if done else None,
        retire_cause=done.retire_cause if done else None,
        reuse=run.reuse if run else None,
        audit_log_id=exit_.execution_id if exit_ else None,
        sandbox_id=run.sandbox_id if run else None,
        sandbox_run=run.sandbox_run if run else None,
        exit_reason=exit_.reason if exit_ else None,
        exit_code=exit_.exit_code if exit_ else None,
        output_sha256=digest,
        failure=failure,
        failure_detail=detail,
    )


def _cpu_seconds() -> float:
    times = os.times()
    return times.user + times.system


# ---------------------------------------------------------------------------
# The summary: everything below reads only the raw file.
# ---------------------------------------------------------------------------


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
class ArmSummary:
    header: BenchHeader
    footer: BenchFooter | None
    planned: int
    measured: int
    ok: int
    failed: int
    """Measured runs that failed, in any way. They count here and not in the latencies."""
    failures: dict[str, int]
    warmup: int
    warmup_failed: int
    warm: int
    cold: int
    off_shape: int
    """Runs that started warm on the cold arm, or not warm on a warm arm."""
    wrong_reuse: int
    reset_outcomes: dict[str, int]
    distinct_outputs: int
    wall: Percentiles
    client_startup: Percentiles
    startup: Percentiles
    execution: Percentiles
    reset: Percentiles
    cycle: Percentiles
    programs_per_second: float | None

    @property
    def arm(self) -> PoolMode:
        return PoolMode(self.header.arm)


@dataclass(frozen=True)
class RawFile:
    arms: tuple[ArmSummary, ...]
    unreadable_lines: int


def load_raw(path: Path) -> RawFile:
    rows: dict[str, _ArmRows] = {}
    unreadable = 0
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
    return RawFile(tuple(summarize(row) for row in rows.values()), unreadable)


def summarize(rows: _ArmRows) -> ArmSummary:
    arm = PoolMode(rows.header.arm)
    measured = [run for run in rows.runs if run.phase == "measured"]
    warmup = [run for run in rows.runs if run.phase == "warmup"]
    good = [run for run in measured if run.failure is None]
    framed = [run for run in measured if run.warm is not None]
    seconds = rows.footer.measured_seconds if rows.footer else None
    return ArmSummary(
        header=rows.header,
        footer=rows.footer,
        planned=rows.header.candidates,
        measured=len(measured),
        ok=len(good),
        failed=len(measured) - len(good),
        failures=dict(Counter(run.failure for run in measured if run.failure is not None)),
        warmup=len(warmup),
        warmup_failed=sum(run.failure is not None for run in warmup),
        warm=sum(run.warm is True for run in framed),
        cold=sum(run.warm is False for run in framed),
        off_shape=sum(run.warm is not _REQUIRED_WARM[arm] for run in framed),
        wrong_reuse=sum((run.reuse or "POOL_REUSE_RESET") != _REQUIRED_REUSE[arm] for run in framed),
        reset_outcomes=dict(Counter(run.reset_outcome or "not reported" for run in framed)),
        distinct_outputs=len({run.output_sha256 for run in good}),
        wall=percentiles(run.wall_ms for run in good),
        client_startup=percentiles(run.client_startup_ms for run in good),
        startup=percentiles(run.startup_ms for run in good),
        execution=percentiles(run.exec_ms for run in good),
        reset=percentiles(run.reset_ms for run in good),
        cycle=percentiles(run.cycle_ms for run in good),
        programs_per_second=len(good) / seconds if seconds else None,
    )


def render_arm(summary: ArmSummary) -> str:
    header, footer = summary.header, summary.footer
    lines = [
        f"## {arm_label(summary.arm)}, session {header.session}",
        "",
        f"- Profile {header.profile}, backend {header.backend}, program {header.program_sha256[:12]} on task "
        f"{header.task}, concurrency {header.concurrency}, shape {header.pool_shape}",
        f"- Server version {header.server_version or NOT_MEASURED} ({header.server_version_source}), "
        f"SDK {header.sdk_version} at {header.sdk_rev}, git {header.git_commit}{' (dirty)' if header.git_dirty else ''}",
        f"- Host {header.hostname}, {header.cpu_count} CPUs, load {_load(header.load_start)} at the start, "
        f"{_load(footer.load_end) if footer else NOT_MEASURED} at the end, client CPU "
        f"{f'{footer.client_cpu_seconds:.1f} s' if footer else NOT_MEASURED}",
        f"- Image resolved via: {header.image_resolved_via or _IMAGE_UNCONFIRMED}",
        f"- Measured {summary.measured} of {summary.planned} planned: {summary.ok} ok, {summary.failed} failed"
        + (f" {summary.failures}" if summary.failures else ""),
        f"- Warmup, left out of everything below: {summary.warmup} runs, {summary.warmup_failed} failed",
        f"- Started warm {summary.warm}, cold {summary.cold}; not what this arm requires: {summary.off_shape}; "
        f"wrong reuse mode: {summary.wrong_reuse}",
        f"- Reset outcomes: {summary.reset_outcomes}",
        f"- Distinct outputs among ok runs: {summary.distinct_outputs}",
        "- Programs per second: "
        + (NOT_MEASURED if summary.programs_per_second is None else f"{summary.programs_per_second:.1f}"),
        f"- Denied syscalls: {NOT_MEASURED}. {DENIED_SYSCALLS_NOTE}",
        f"- Blocked network attempts: {blocked_net_note(header.network)}",
    ]
    if footer is None or not footer.completed:
        lines.append("- **This arm did not finish. The numbers cover only what it logged.**")
    lines += [f"- **Warning: {warning}**" for warning in _load_warnings(header)]
    lines += ["", "| Time, ok runs only, in ms | Count | Not reported | p50 | p90 | p99 | Max |", "|---|---|---|---|---|---|---|"]
    for name, values in (
        ("Wall-clock, start to exit (client)", summary.wall),
        ("Startup (Vora)", summary.startup),
        ("Startup (client)", summary.client_startup),
        ("Execution (client)", summary.execution),
        ("This run's reset (Vora)", summary.reset),
        ("Start to end of stream (client)", summary.cycle),
    ):
        cells = " | ".join(_ms(value) for value in (values.p50, values.p90, values.p99, values.max))
        lines.append(f"| {name} | {values.count} | {values.missing} | {cells} |")
    return "\n".join(lines) + "\n"


def render_summary(raw: RawFile) -> str:
    lines = ["# Experiment 1 raw results", ""]
    if not raw.arms:
        lines.append("This file holds no complete header.")
    if raw.unreadable_lines:
        lines += [f"**{raw.unreadable_lines} lines of this file could not be read.**", ""]
    lines += _comparison(raw.arms)
    lines += [render_arm(arm) for arm in raw.arms]
    return "\n".join(lines) + "\n"


def _comparison(arms: Sequence[ArmSummary]) -> list[str]:
    if not arms:
        return []
    lines = [
        "| Arm | Sessions | Wall p50, ms (range) | Wall p99, ms (range) | Programs/s (range) | Failed | Off shape |",
        "|---|---|---|---|---|---|---|",
    ]
    notes: list[str] = []
    for mode in PoolMode:
        sessions = [arm for arm in arms if arm.arm is mode]
        if not sessions:
            continue
        lines.append(
            f"| {arm_label(mode)} | {len(sessions)} "
            f"| {_median_range(arm.wall.p50 for arm in sessions)} "
            f"| {_median_range(arm.wall.p99 for arm in sessions)} "
            f"| {_median_range(arm.programs_per_second for arm in sessions)} "
            f"| {sum(arm.failed for arm in sessions)} of {sum(arm.measured for arm in sessions)} "
            f"| {sum(arm.off_shape for arm in sessions)} |"
        )
        if len(sessions) < MIN_SESSIONS:
            notes.append(f"{mode.value} has {len(sessions)} sessions: fewer than {MIN_SESSIONS} can't show it reproduces.")
    if any(arm.header.image_resolved_via is None for arm in arms):
        notes.append(f"Image source: {_IMAGE_UNCONFIRMED}.")
    if len({(arm.header.program_sha256, arm.header.task, arm.header.concurrency, arm.header.backend) for arm in arms}) > 1:
        notes.append("These sessions differ in program, task, concurrency or backend, so the arms are not comparable.")
    return [*lines, "", *notes, ""]


def _median_range(values: Iterable[float | None]) -> str:
    reported = [value for value in values if value is not None]
    if not reported:
        return NOT_MEASURED
    return f"{statistics.median(reported):.1f} ({min(reported):.1f} to {max(reported):.1f})"


def _load(load: Sequence[float]) -> str:
    return " ".join(f"{value:.2f}" for value in load)


def _ms(value: float | None) -> str:
    return NOT_MEASURED if value is None else f"{value:.1f}"

