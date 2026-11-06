"""pool_batch against a fake vora-api: what a pooled run stores, and how each refusal is handled."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fake_pools import ADMIN_KEY, TENANT_KEY, FakePools, Frames, LivePool, Placement, Refuse, stdout_frame
from vora import GatewayTimeoutError, Pool, PoolNotLoadedError, PoolNotOnRunnerError, RateLimitedError, Vora

from vora_arc import client, model, schedule
from vora_arc.client import PoolMode, SandboxInfrastructureError, connect, open_pool, pool_batch, pool_shape
from vora_arc.model import GridStatus, Pair, RunStatus, Task, Verdict
from vora_arc.profile import DEFAULT_PROFILE_PATH, load_profile
from vora_arc.schedule import InfraFailure, Judgement, program_sha256

ROOT = Path(__file__).resolve().parents[1]
PROFILE = load_profile(DEFAULT_PROFILE_PATH)
PROGRAM = "def transform(grid):\n    return [row[::-1] for row in grid]\n"
TASK = Task(
    id="t1",
    train=(Pair(((1, 2),), ((2, 1),)), Pair(((3, 4),), ((4, 3),))),
    test=(model.TestCase(((5, 6),), None),),
)
RIGHT = stdout_frame(
    {"index": 0, "status": "OK", "output": [[2, 1]], "error": None, "wall_ms": 1},
    {"index": 1, "status": "OK", "output": [[4, 3]], "error": None, "wall_ms": 1},
    {"index": 2, "status": "OK", "output": [[6, 5]], "error": None, "wall_ms": 1},
    {"done": True, "stderr_tail": "printed\n"},
)
RUN_FRAME = {"run": {"sandboxId": "sbx_1", "executionId": "exe_run", "warm": True, "sandboxRun": 2}}
PARTIAL = stdout_frame({"index": 0, "status": "OK", "output": [[2, 1]], "error": None, "wall_ms": 1})


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakePools]:
    server = FakePools()
    with server.running():
        monkeypatch.setenv("VORA_API_URL", server.url)
        monkeypatch.setenv("VORA_API_KEY", TENANT_KEY)
        yield server


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "RETRY_DELAYS_S", (0.0, 0.0, 0.0))


@pytest.fixture
async def vora(fake: FakePools) -> AsyncIterator[Vora]:
    async with connect(PROFILE) as connected:
        yield connected


async def warm_pool(vora: Vora, size: int = 2) -> Pool:
    return await vora.pools.declare("py", image="vora/arc", cpu="1000m", memory="256Mi", pids=64, size=size, max_size=size)


async def run(vora: Vora) -> model.BatchResult:
    return await pool_batch(await warm_pool(vora), PROFILE, PROGRAM, TASK, correlation_id="t1/c1")


async def test_a_warm_run_stores_what_vora_reported_about_it(fake: FakePools, vora: Vora) -> None:
    fake.runs.append(
        Frames(
            (
                {"run": {"sandboxId": "sbx_1", "executionId": "exe_run", "warm": True, "resetMs": "7", "sandboxRun": 3}},
                RIGHT,
                {
                    "exit": {
                        "reason": "EXITED",
                        "executionId": "exe_exit",
                        "usage": {"cpuMillis": "21", "memoryPeakBytes": "2048", "memoryPeakScope": "PEAK_SCOPE_WINDOW"},
                    }
                },
                {"runDone": {"outcome": "POOL_RESET_OK", "resetMs": "3"}},
            )
        )
    )

    result = await run(vora)

    assert result.run_status is RunStatus.COMPLETED
    assert [(grid.index, grid.is_test, grid.output) for grid in result.grids] == [
        (0, False, ((2, 1),)),
        (1, False, ((4, 3),)),
        (2, True, ((6, 5),)),
    ]
    assert result.program_sha256 == program_sha256(PROGRAM)
    assert result.stderr_tail == "printed\n"
    assert result.warm_start is True
    assert result.reset_ms == 3, "the column holds this run's own reset, from run_done"
    assert result.prepared_reset_ms == 7, "the reset that prepared the member stays apart from it"
    assert result.audit_log_id == "exe_exit"
    assert result.sandbox_id == "sbx_1"
    assert result.sandbox_run == 3
    assert (result.cpu_ms, result.peak_mem_bytes) == (21, 2048)
    assert result.reset_outcome == "POOL_RESET_OK"


async def test_a_cold_pool_run_is_not_warm_and_has_no_reset(fake: FakePools, vora: Vora) -> None:
    fake.runs.append(
        Frames(
            (
                {"run": {"sandboxId": "sbx_1", "startupMs": "185", "sandboxRun": 1}},
                RIGHT,
                {"exit": {"reason": "EXITED", "executionId": "exe_1"}},
                {"runDone": {"outcome": "POOL_RESET_RETIRED", "retireCause": "shrink"}},
            )
        )
    )

    result = await run(vora)

    assert result.warm_start is False
    assert result.reset_ms is None
    assert result.prepared_reset_ms is None
    assert result.reset_outcome == "POOL_RESET_RETIRED"


async def test_what_vora_left_out_stays_none_and_never_becomes_zero(fake: FakePools, vora: Vora) -> None:
    fake.runs.append(Frames(({"run": {}}, RIGHT, {"exit": {"reason": "EXITED"}}, {"runDone": {}})))

    result = await run(vora)

    assert result.warm_start is False, "protojson leaves out false, and the SDK reads that as false"
    assert result.sandbox_id is None
    assert result.reset_ms is None
    assert result.prepared_reset_ms is None
    assert result.audit_log_id is None
    assert result.cpu_ms is None
    assert result.peak_mem_bytes is None
    assert result.reset_outcome is None


async def test_a_lifetime_peak_is_not_reported_as_this_runs_peak(fake: FakePools, vora: Vora) -> None:
    usage = {"cpuMillis": "21", "memoryPeakBytes": "2048", "memoryPeakScope": "PEAK_SCOPE_LIFETIME"}
    fake.runs.append(Frames((RUN_FRAME, RIGHT, {"exit": {"reason": "EXITED", "usage": usage}})))

    result = await run(vora)

    assert result.peak_mem_bytes is None


async def test_a_stream_lost_after_exit_keeps_the_result_with_no_reset(fake: FakePools, vora: Vora) -> None:
    fake.runs.append(Frames((RUN_FRAME, RIGHT, {"exit": {"reason": "EXITED", "executionId": "exe_1"}})))

    result = await run(vora)

    assert result.run_status is RunStatus.COMPLETED
    assert result.audit_log_id == "exe_1"
    assert result.reset_ms is None
    assert result.reset_outcome is None


@pytest.mark.parametrize(
    ("reason", "usage", "expected"),
    [
        ("EXITED", {}, RunStatus.COMPLETED),
        ("TIMEOUT_EXCEEDED", {}, RunStatus.KILLED_TIMEOUT),
        ("OOM_KILLED", {"oomKills": "1"}, RunStatus.KILLED_OOM),
        ("PIDS_LIMIT_EXCEEDED", {"pidsLimitHits": "2"}, RunStatus.POLICY_VIOLATION),
        ("EXITED", {"pidsLimitHits": "2"}, RunStatus.POLICY_VIOLATION),
    ],
)
async def test_how_a_run_ended_decides_its_status(
    fake: FakePools, vora: Vora, reason: str, usage: dict[str, str], expected: RunStatus
) -> None:
    fake.runs.append(Frames((RUN_FRAME, RIGHT, {"exit": {"reason": reason, "usage": usage}})))

    assert (await run(vora)).run_status is expected


async def test_an_exit_reason_about_vora_is_no_verdict_on_the_program(fake: FakePools, vora: Vora) -> None:
    fake.runs.append(Frames((RUN_FRAME, RIGHT, {"exit": {"reason": "RUNTIME_FAILURE"}})))

    with pytest.raises(SandboxInfrastructureError, match="RUNTIME_FAILURE"):
        await run(vora)


async def test_a_stream_broken_before_exit_is_never_run_again(fake: FakePools, vora: Vora) -> None:
    fake.runs.append(Frames((RUN_FRAME, PARTIAL, {"error": {"code": "run_failed", "message": "gone"}})))

    with pytest.raises(SandboxInfrastructureError, match="without an exit record"):
        await run(vora)

    assert len(fake.calls("POST", "/run")) == 1


async def test_a_kill_that_took_the_stream_down_is_read_from_the_audit_trail(fake: FakePools, vora: Vora) -> None:
    fake.runs.append(Frames((RUN_FRAME, PARTIAL, {"error": {"code": "run_failed", "message": "gone"}})))
    fake.audit["sbx_1"] = [{"executionId": "exe_other"}, {"executionId": "exe_run", "oomKills": "1"}]

    result = await run(vora)

    assert result.run_status is RunStatus.KILLED_OOM
    assert [grid.status for grid in result.grids] == [GridStatus.OK, GridStatus.ERROR, GridStatus.ERROR]
    assert result.audit_log_id == "exe_run"
    assert len(fake.calls("POST", "/run")) == 1


async def test_a_full_pool_is_tried_again_and_nothing_had_run(fake: FakePools, vora: Vora) -> None:
    fake.runs.extend([Refuse(429, "pool full"), Refuse(503, "runner loading")])

    result = await run(vora)

    assert result.run_status is RunStatus.COMPLETED
    assert len(fake.calls("POST", "/run")) == 3


async def test_a_retry_waits_as_long_as_the_api_asked(
    fake: FakePools, vora: Vora, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    fake.runs.append(Refuse(429, "pool full", retry_after="4"))

    await run(vora)

    assert waits == [4.0]


async def test_a_pool_that_stays_full_raises_after_the_last_retry(fake: FakePools, vora: Vora) -> None:
    fake.runs.extend([Refuse(429, "pool full")] * 4)

    with pytest.raises(RateLimitedError):
        await run(vora)

    assert len(fake.calls("POST", "/run")) == 4


async def test_a_runner_too_slow_to_answer_is_not_run_again(fake: FakePools, vora: Vora) -> None:
    fake.runs.append(Refuse(504, "the runner did not answer in time"))

    with pytest.raises(GatewayTimeoutError):
        await run(vora)

    assert len(fake.calls("POST", "/run")) == 1


async def test_a_pool_the_runner_refused_is_never_retried(fake: FakePools, vora: Vora) -> None:
    pool = await warm_pool(vora)
    fake.runs.append(Refuse(409, "pool is not loaded on this runner: backend_missing", state="POOL_NOT_LOADED"))

    with pytest.raises(PoolNotLoadedError):
        await pool_batch(pool, PROFILE, PROGRAM, TASK, correlation_id="t1/c1")

    assert len(fake.calls("POST", "/run")) == 1


async def test_a_pool_the_runner_lost_is_not_retried(fake: FakePools, vora: Vora) -> None:
    pool = await warm_pool(vora)
    fake.runs.append(Refuse(409, "pool not on runner", state="POOL_NOT_ON_RUNNER"))

    with pytest.raises(PoolNotOnRunnerError):
        await pool_batch(pool, PROFILE, PROGRAM, TASK, correlation_id="t1/c1")

    assert len(fake.calls("POST", "/run")) == 1


async def test_a_cancelled_run_leaves_the_stream_so_the_member_goes_back(fake: FakePools, vora: Vora) -> None:
    pool = await warm_pool(vora)
    fake.runs.append(Frames((RUN_FRAME,), hold=True))
    job = asyncio.create_task(pool_batch(pool, PROFILE, PROGRAM, TASK, correlation_id="t1/c1"))
    while not fake.calls("POST", "/run"):
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)

    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job

    assert await asyncio.to_thread(fake.client_left.wait, 5), "the connection stayed open, holding the member"


async def test_one_programs_vora_failure_is_reported_and_the_others_still_run(fake: FakePools, vora: Vora) -> None:
    pool = await warm_pool(vora)
    fake.runs.extend([Refuse(409, "not loaded", state="POOL_ACTIVE")])
    other = "def transform(grid):\n    return [list(reversed(row)) for row in grid]\n"

    results = await schedule.schedule(vora, PROFILE, TASK, [PROGRAM, other], max_concurrency=1, pool=pool)

    failed = results[program_sha256(PROGRAM)].result
    assert isinstance(failed, InfraFailure) and "ConflictError" in failed.error
    survived = results[program_sha256(other)].result
    assert isinstance(survived, Judgement) and survived.outcome.verdict is Verdict.PASSED
    assert all(run.warm_start for run in survived.runs), "the judge and its re-run both used the pool"
    assert len(survived.runs) == 2


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (PoolMode.COLD, {"size": 0, "maxSize": 8}),
        (PoolMode.WARM, {"size": 4, "maxSize": 4, "maxRuns": 100}),
        (PoolMode.WARM_NO_RESET, {"size": 4, "maxSize": 4, "maxRuns": 100, "reuse": "POOL_REUSE_UNSAFE_NO_RESET"}),
    ],
)
async def test_each_arm_declares_the_designs_shape_and_nothing_else_differs(
    fake: FakePools, vora: Vora, mode: PoolMode, expected: dict[str, Any]
) -> None:
    async with Vora(api_key=ADMIN_KEY) as admin:
        tenant = "tenant-a" if mode is PoolMode.WARM_NO_RESET else None
        async with open_pool(vora, PROFILE, "py", mode, 4, admin=admin, tenant_id=tenant):
            pass

    body = fake.calls("PUT")[0].body
    assert body is not None
    shape = {key: body[key] for key in ("size", "maxSize", "maxRuns", "reuse") if key in body}
    assert shape == expected
    assert body["sandbox"]["image"] == PROFILE.image
    assert body["sandbox"]["backend"] == PROFILE.backend
    assert body["sandbox"]["network"] == {"mode": "NETWORK_NONE"}
    assert body["sandbox"]["resources"] == {
        "cpuMillis": str(PROFILE.cpu_millis),
        "memoryBytes": str(PROFILE.memory_bytes),
        "pids": str(PROFILE.pids),
    }
    assert "ttlSeconds" not in body["sandbox"], "a pool refuses a template with a TTL"


async def test_only_the_no_reset_shape_asks_for_unsafe_reuse() -> None:
    assert pool_shape(PoolMode.WARM_NO_RESET, 2)["reuse"] == "unsafe_no_reset"
    assert "reuse" not in pool_shape(PoolMode.WARM, 2)
    assert "reuse" not in pool_shape(PoolMode.COLD, 2)


async def test_an_admin_declares_the_unsafe_pool_and_the_tenants_key_runs_on_it(fake: FakePools, vora: Vora) -> None:
    async with Vora(api_key=ADMIN_KEY) as admin:
        async with open_pool(vora, PROFILE, "py", PoolMode.WARM_NO_RESET, 2, admin=admin, tenant_id="tenant-a") as pool:
            await pool_batch(pool, PROFILE, PROGRAM, TASK, correlation_id="t1/c1")

    declare = fake.calls("PUT")[0]
    assert declare.key == ADMIN_KEY
    assert declare.body is not None and declare.body["tenantId"] == "tenant-a"
    assert fake.calls("POST", "/run")[0].key == TENANT_KEY
    assert fake.calls("GET")[0].key == TENANT_KEY
    assert fake.calls("DELETE")[0].key == TENANT_KEY


async def test_the_unsafe_arm_needs_an_admin_key(fake: FakePools, vora: Vora) -> None:
    with pytest.raises(SystemExit, match="VORA_ADMIN_API_KEY"):
        async with open_pool(vora, PROFILE, "py", PoolMode.WARM_NO_RESET, 2):
            pass

    assert fake.calls("PUT") == []


async def test_a_refused_spec_says_why_and_which_profile(fake: FakePools, vora: Vora) -> None:
    fake.declare_error = (400, 'pool: invalid spec: pids must be >= 64 on backend "gvisor"')

    with pytest.raises(SystemExit, match=r"python-arc.*pids must be >= 64"):
        async with open_pool(vora, PROFILE, "py", PoolMode.WARM, 2):
            pass


async def test_a_pool_is_deleted_even_when_the_work_inside_failed(fake: FakePools, vora: Vora) -> None:
    with pytest.raises(ValueError, match="bug"):
        async with open_pool(vora, PROFILE, "py", PoolMode.WARM, 2):
            raise ValueError("bug")

    assert len(fake.calls("DELETE")) == 1


async def test_a_backend_that_cannot_reset_is_refused_by_name_and_not_read_as_a_fit(fake: FakePools, vora: Vora) -> None:
    # Vora without vorash/vora#150 can't reset a gVisor member, and answers a warm declare with this.
    fake.declare_error = (400, 'pool: backend cannot reset sandboxes: "gvisor"')

    with pytest.raises(SystemExit, match=r'python-arc.*backend cannot reset sandboxes: "gvisor"'):
        async with open_pool(vora, PROFILE, "py", PoolMode.WARM, 2):
            pass

    assert fake.calls("POST", "/run") == []


async def test_connections_stay_open_past_httpxs_default_of_twenty(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[httpx.Limits] = []
    real = httpx.AsyncClient

    def client_with(*args: Any, limits: httpx.Limits, **kwargs: Any) -> httpx.AsyncClient:
        built.append(limits)
        return real(*args, limits=limits, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_with)
    async with connect(PROFILE):
        pass

    assert built[0].max_keepalive_connections is None
    assert built[0].max_connections is None


@pytest.mark.parametrize("path", sorted((ROOT / "profiles").glob("*.toml")), ids=lambda path: path.stem)
def test_every_shipped_profile_meets_the_rules_of_a_pool_spec(path: Path) -> None:
    """Network mode none, and a pids limit at or above the backend's floor. This says nothing about
    whether the backend can reset: on gVisor that needs a Vora release with vorash/vora#150."""
    profile = load_profile(path)
    assert profile.network == "none"
    assert profile.pids >= {"bwrap": 12, "gvisor": 64}[profile.backend]


def _pool_spec_source() -> Path:
    return Path(os.environ.get("VORA_REPO", ROOT.parent / "vora")) / "internal" / "pool" / "spec.go"


@pytest.mark.skipif(not _pool_spec_source().exists(), reason="needs a Vora checkout; set VORA_REPO")
def test_the_pids_floors_above_are_voras_own() -> None:
    source = _pool_spec_source().read_text()
    assert "minPidsBwrap  = 12" in source
    assert "minPidsGvisor = 64" in source
    assert "t.Network.Mode != runtime.NetworkNone" in source
    assert 'errors.New("pool: backend cannot reset sandboxes")' in source


def _golden() -> Path:
    return Path(os.environ.get("VORA_REPO", ROOT.parent / "vora")) / "sdk" / "testdata" / "pool_wire.json"


@pytest.mark.skipif(not _golden().exists(), reason="needs a Vora checkout; set VORA_REPO")
@pytest.mark.parametrize(
    ("scenario", "warm", "reset", "prepared", "audit"),
    [
        ("warm_reset", True, 3, 7, "exe_01M6M3D3FRG49JM5BK3MD9Q0X0"),
        ("cold_first_run_nonzero_exit", False, None, None, "exe_01M6M3D3FRG49JM5BK3MD9Q0X0"),
        ("unsafe_no_reset", True, None, None, "exe_01M6M3D3FRG49JM5BK3MD9Q0X0"),
    ],
)
async def test_the_bytes_the_real_api_sends_fill_the_same_fields(
    fake: FakePools, vora: Vora, scenario: str, warm: bool, reset: int | None, prepared: int | None, audit: str
) -> None:
    lines = json.loads(_golden().read_text())["runs"][scenario]["lines"]
    fake.runs.append(Frames(tuple(json.loads(line) for line in lines)))

    result = await run(vora)

    assert (result.warm_start, result.reset_ms, result.prepared_reset_ms, result.audit_log_id) == (warm, reset, prepared, audit)


def test_the_fake_only_says_what_the_real_api_says_about_a_run() -> None:
    if not _golden().exists():
        pytest.skip("needs a Vora checkout; set VORA_REPO")
    golden = json.loads(_golden().read_text())["runs"]
    keys: dict[str, set[str]] = {}
    for scenario in golden.values():
        for line in scenario.get("lines") or []:
            for frame, body in json.loads(line).items():
                if isinstance(body, dict):
                    keys.setdefault(frame, set()).update(body)
    fake = FakePools()
    stdin: dict[str, Any] = {"inputs": []}
    for spec in ({"size": 0}, {"size": 1}, {"size": 1, "reuse": "POOL_REUSE_UNSAFE_NO_RESET"}, {"size": 1, "maxRuns": 2}):
        pool = LivePool.from_spec(spec)
        for _ in range(2):
            placement = pool.borrow()
            frames = [*fake.run_frames(spec, stdin, placement), {"runDone": pool.check_in(placement.member)}]
            for frame in frames:
                for name, body in frame.items():
                    if isinstance(body, dict):
                        assert set(body) <= keys[name], f"{name} has keys the real API never sends"


def _settled(check: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + 5
    while not check() and time.monotonic() < deadline:
        time.sleep(0.001)
    return check()


def test_the_fake_retires_a_member_at_max_runs_and_gives_each_member_its_own_id() -> None:
    pool = LivePool.from_spec({"size": 1, "maxSize": 1, "maxRuns": 2}, destroy_s=0.02)

    first = pool.borrow()
    assert (first.warm, first.member.id, first.member.runs) == (True, "sbx_1", 1)
    assert pool.check_in(first.member)["outcome"] == "POOL_RESET_OK"
    second = pool.borrow()
    assert (second.warm, second.member.id, second.member.runs) == (True, "sbx_1", 2)
    assert pool.check_in(second.member) == {"outcome": "POOL_RESET_RETIRED", "retireCause": "max_runs"}

    third = pool.borrow()

    assert (third.warm, third.member.id, third.member.runs) == (False, "sbx_2", 1), "a waiter with nothing in flight starts cold"
    assert pool.retired == {"max_runs": 1}


def test_the_fake_replaces_a_retired_member_in_the_background_when_no_one_waits() -> None:
    pool = LivePool.from_spec({"size": 1, "maxSize": 1, "maxRuns": 1})
    first = pool.borrow()
    pool.check_in(first.member)

    assert _settled(lambda: bool(pool.idle))

    replacement = pool.borrow()
    assert (replacement.warm, replacement.member.id, replacement.member.runs) == (True, "sbx_2", 1)


def test_the_fake_queues_a_borrower_while_another_run_is_in_flight() -> None:
    pool = LivePool.from_spec({"size": 1, "maxSize": 2})
    first = pool.borrow()
    second: list[Placement] = []
    waiter = threading.Thread(target=lambda: second.append(pool.borrow()))
    waiter.start()

    assert _settled(lambda: bool(pool.waiters)), "a slot is free, but a run in flight will bring a member back"
    assert not second

    pool.check_in(first.member)
    waiter.join(5)

    assert (second[0].warm, second[0].member.id) == (True, "sbx_1")
    assert pool.max_busy == 1
