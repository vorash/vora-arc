"""`vora-arc bench`: one arm of experiment 1, and a summary rebuilt from raw files.

The three arms run the same corpus in the same order at the same concurrency, and differ
only in pool shape (`client.pool_shape`). Every number in a summary comes from the raw
files. See docs/experiment-1.md for what limits each arm's number.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import platform
import secrets
import subprocess
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, TextIO

import httpx
from vora import Pool, Vora, VoraError

from .bench_summary import (
    IMAGE_UNCONFIRMED,
    BenchFooter,
    BenchHeader,
    BenchRun,
    Phase,
    arm_label,
    corpus_line,
    load_average,
    load_raw,
    load_warnings,
    render_arm,
)
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
from .corpus import MIX_DENOMINATOR, Candidate, Corpus
from .model import RunStatus, Task, redact_userinfo
from .profile import Profile
from .report import NOT_MEASURED
from .verify import verify

ROOT = Path(__file__).resolve().parents[2]
ADMIN_KEY_ENV = "VORA_ADMIN_API_KEY"
TENANT_ENV = "VORA_ARC_TENANT_ID"

# Long enough that a slow replacement member shows as a slow run, not as a refusal.
# The same on every arm, because it isn't part of a pool's shape.
BORROW_TIMEOUT_MS = 60_000
READY_TIMEOUT_S = 120.0
READY_POLL_S = 0.1
READ_VERSION_TIMEOUT_S = 30.0
MAX_DETAIL_CHARS = 500


@dataclass(frozen=True)
class BenchSettings:
    arm: PoolMode
    concurrency: int
    image_resolved_via: str | None
    server_version: str | None


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
    tasks: Mapping[str, Task]
    settings: BenchSettings
    session: str
    log: RawLog


async def run_bench(
    profile: Profile,
    corpus: Corpus,
    warmup: Sequence[Candidate],
    tasks: Mapping[str, Task],
    settings: BenchSettings,
    raw_path: Path,
    *,
    vora: Vora,
) -> int:
    """Run one arm and append it to ``raw_path``. Non-zero if Vora failed or the arm is broken."""
    session = secrets.token_hex(3)
    pool_name = f"vora-arc-bench-{settings.arm.value}-{session}"
    tenant_id = os.environ.get(TENANT_ENV) or None
    async with _admin_client() as admin:
        version, version_source = await _server_version(settings.server_version)
        header = _header(profile, corpus, warmup, tasks, settings, session, pool_name, version, version_source)
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
                    job = _Job(pool, profile, tasks, settings, session, log)
                    ready_ms = await _wait_until_ready(pool, settings)
                    await _run_phase(job, "warmup", warmup)
                    started = time.perf_counter()
                    await _run_phase(job, "measured", corpus.candidates)
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
    return 1 if summary.failed else 0


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
    corpus: Corpus,
    warmup: Sequence[Candidate],
    tasks: Mapping[str, Task],
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
        candidates=len(corpus.candidates),
        warmup=len(warmup),
        concurrency=settings.concurrency,
        corpus_seed=corpus.seed,
        corpus_sha256=corpus.sha256,
        corpus_mix={name.value: parts for name, parts in corpus.mix.items()},
        corpus_denominator=MIX_DENOMINATOR,
        corpus_counts={name.value: count for name, count in corpus.counts.items()},
        corpus_distinct_programs={name.value: count for name, count in corpus.distinct_programs.items()},
        tasks_sha256=_tasks_sha256(tasks),
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


def _tasks_sha256(tasks: Mapping[str, Task]) -> str:
    digest = hashlib.sha256()
    for task_id in sorted(tasks):
        digest.update(json.dumps(asdict(tasks[task_id])).encode())
    return digest.hexdigest()


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
    print(f"corpus: {corpus_line(header)}")
    print(f"{header.candidates} measured runs after {header.warmup} warmup runs, at concurrency {header.concurrency}")
    print(f"server version: {header.server_version or NOT_MEASURED} ({header.server_version_source})")
    print(f"sdk: {header.sdk_version} at {header.sdk_rev}; git: {header.git_commit}{' (dirty)' if header.git_dirty else ''}")
    print(f"load average on {header.hostname}: {load_average(header.load_start)}, {header.cpu_count} CPUs")
    print(f"image resolved via: {header.image_resolved_via or IMAGE_UNCONFIRMED}")
    for warning in load_warnings(header):
        print(f"warning: {warning}")


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


async def _run_phase(job: _Job, phase: Phase, candidates: Sequence[Candidate]) -> None:
    next_candidates = iter(candidates)

    async def worker() -> None:
        for candidate in next_candidates:
            job.log.write("run", await _one_run(job, phase, candidate))

    async with asyncio.TaskGroup() as group:
        for _ in range(job.settings.concurrency):
            group.create_task(worker())


async def _one_run(job: _Job, phase: Phase, candidate: Candidate) -> BenchRun:
    task = job.tasks[candidate.task_id]
    stdin, is_test = batch_request(job.profile, candidate.program, task)
    started_at = time.time()
    began = time.perf_counter()
    correlation_id = f"bench/{job.session}/{phase}/{candidate.index}"
    try:
        record = await run_in_pool(job.pool, job.profile, stdin, is_test)
    except VoraError as error:
        return _refused(job, phase, candidate, started_at, (time.perf_counter() - began) * 1000, error)
    judgement = await _judge(job, candidate, task, is_test, correlation_id, record)
    return _measured(job, phase, candidate, started_at, record, judgement)


@dataclass(frozen=True)
class _Judgement:
    verdict: str | None
    infra_failure: str | None
    detail: str | None
    output_sha256: str | None


async def _judge(
    job: _Job, candidate: Candidate, task: Task, is_test: tuple[bool, ...], correlation_id: str, record: PoolRunRecord
) -> _Judgement:
    """A candidate failing verification is its result. Only a run with no result is a failed run."""
    try:
        result = await pool_result(job.pool, job.profile, candidate.program, is_test, correlation_id, record)
    except SandboxInfrastructureError as error:
        code = record.failure.code if record.failure else f"exit_reason:{record.exit.reason if record.exit else None}"
        return _Judgement(None, code, str(error)[:MAX_DETAIL_CHARS], None)
    if result.run_status is RunStatus.COMPLETED and record.output.done is None:
        # The runner ends every completed run with a done line, whatever the program does.
        # Without it the runner itself failed, and the "crashed" this would earn would flatter the arm.
        return _Judgement(None, "no_runner_result", result.stderr_tail[-MAX_DETAIL_CHARS:] or None, None)
    outcome = verify(task, candidate.program, result)
    outputs = json.dumps([[grid.index, grid.status, grid.output] for grid in result.grids])
    digest = hashlib.sha256(outputs.encode()).hexdigest()
    first_error = next((grid.error for grid in result.grids if grid.error), None)
    return _Judgement(str(outcome.verdict), None, first_error[:MAX_DETAIL_CHARS] if first_error else None, digest)


def _refused(
    job: _Job, phase: Phase, candidate: Candidate, started_at: float, cycle_ms: float, error: VoraError
) -> BenchRun:
    return BenchRun(
        session=job.session,
        arm=job.settings.arm.value,
        phase=phase,
        index=candidate.index,
        candidate_class=candidate.candidate_class.value,
        task=candidate.task_id,
        program_sha256=candidate.program_sha256,
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
        verdict=None,
        infra_failure=type(error).__name__,
        failure_detail=str(error)[:MAX_DETAIL_CHARS],
    )


def _measured(
    job: _Job, phase: Phase, candidate: Candidate, started_at: float, record: PoolRunRecord, judgement: _Judgement
) -> BenchRun:
    run, exit_, done = record.run, record.exit, record.done
    return BenchRun(
        session=job.session,
        arm=job.settings.arm.value,
        phase=phase,
        index=candidate.index,
        candidate_class=candidate.candidate_class.value,
        task=candidate.task_id,
        program_sha256=candidate.program_sha256,
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
        audit_log_id=exit_.execution_id if exit_ else run.execution_id if run else None,
        sandbox_id=run.sandbox_id if run else None,
        sandbox_run=run.sandbox_run if run else None,
        exit_reason=exit_.reason if exit_ else None,
        exit_code=exit_.exit_code if exit_ else None,
        output_sha256=judgement.output_sha256,
        verdict=judgement.verdict,
        infra_failure=judgement.infra_failure,
        failure_detail=judgement.detail,
    )


def _cpu_seconds() -> float:
    times = os.times()
    return times.user + times.system
