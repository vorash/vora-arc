"""Spec section 5: each hostile program in tests/hostile/ runs in a real Vora sandbox and is contained.

These programs are never run on the host. Every test needs VORA_API_URL and VORA_API_KEY.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from vora import Pool, Vora

from vora_arc import model
from vora_arc.client import connect, pool_batch, pool_template, run_batch
from vora_arc.model import BatchResult, GridStatus, Pair, RunStatus, Task
from vora_arc.profile import load_profile

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(
        not (os.environ.get("VORA_API_URL") and os.environ.get("VORA_API_KEY")),
        reason="needs a Vora sandbox host: set VORA_API_URL and VORA_API_KEY",
    ),
]

HOSTILE = Path(__file__).parent / "hostile"
PROFILE = load_profile()
# docs/pools.md explains these three. Strict, so that either changing in Vora shows up here.
WRITABLE_BY_DESIGN = (
    "Vora binds /workspace and /root read-write by design: its file API serves them. "
    "What holds on a pool is test_a_write_does_not_survive_into_the_next_run"
)
NO_TMPFS_SIZE = (
    "Vora gives /tmp no size option, so 32 MB fits. test_filling_tmp_runs_into_the_memory_limit shows what bounds it, "
    "and test_a_write_does_not_survive_into_the_next_run that the next run starts clean"
)
# One cell per path, in the order find_hostile_files.py checks them.
WRITERS = {"write_workspace": 0, "write_root_home": 1, "fill_tmp": 2}

# Inputs are marked by their first cell (0, 1, 2) so a program can misbehave on one of them.
TASK = Task(
    id="hostile",
    train=(Pair(((0,),), ((0,),)), Pair(((1,),), ((1,),))),
    test=(model.TestCase(((2,),), None),),
)


@pytest.fixture
async def vora() -> AsyncIterator[Vora]:
    async with connect(PROFILE) as client:
        yield client


async def run(vora: Vora, name: str) -> BatchResult:
    program = (HOSTILE / f"{name}.py").read_text()
    return await run_batch(vora, PROFILE, program, TASK, correlation_id=f"hostile/{name}")


def statuses(result: BatchResult) -> list[GridStatus]:
    return [grid.status for grid in result.grids]


@pytest.mark.parametrize("name", ["infinite_loop", "infinite_loop_native"])
async def test_infinite_loop_times_out_and_the_other_inputs_still_report(vora: Vora, name: str) -> None:
    result = await run(vora, name)

    assert result.run_status in (RunStatus.COMPLETED, RunStatus.KILLED_TIMEOUT)
    assert statuses(result) == [GridStatus.OK, GridStatus.OK, GridStatus.TIMEOUT]


async def test_allocating_2gb_is_killed_at_the_memory_cap(vora: Vora) -> None:
    result = await run(vora, "allocate_2gb")

    assert result.run_status is RunStatus.KILLED_OOM
    assert result.peak_mem_bytes is not None
    assert result.peak_mem_bytes <= PROFILE.memory_bytes


async def test_fork_bomb_is_contained(vora: Vora) -> None:
    result = await run(vora, "fork_bomb")

    if PROFILE.backend == "gvisor":
        # gVisor's guest processes are not host processes, so the pids cgroup
        # (which counts runsc's own threads) never trips; the bomb runs into
        # the memory cap instead. Either way the run is killed, not the host.
        assert result.run_status in (RunStatus.POLICY_VIOLATION, RunStatus.KILLED_OOM)
    else:
        assert result.run_status is RunStatus.POLICY_VIOLATION


@pytest.mark.parametrize("name", ["outbound_http", "dns_lookup"])
async def test_network_access_fails_inside_the_program(vora: Vora, name: str) -> None:
    # Network mode none has no interfaces, so Vora sees no attempt to count.
    result = await run(vora, name)

    assert result.run_status is RunStatus.COMPLETED
    assert statuses(result) == [GridStatus.ERROR] * 3


@pytest.mark.parametrize(
    "name",
    [
        "write_slash",
        "write_usr",
        pytest.param("write_workspace", marks=pytest.mark.xfail(strict=True, reason=WRITABLE_BY_DESIGN)),
        pytest.param("write_root_home", marks=pytest.mark.xfail(strict=True, reason=WRITABLE_BY_DESIGN)),
    ],
)
async def test_writing_outside_tmp_fails(vora: Vora, name: str) -> None:
    result = await run(vora, name)

    assert result.run_status is RunStatus.COMPLETED
    assert statuses(result) == [GridStatus.ERROR] * 3


@pytest.mark.xfail(strict=True, reason=NO_TMPFS_SIZE)
async def test_filling_tmp_past_16mb_fails(vora: Vora) -> None:
    result = await run(vora, "fill_tmp")

    assert statuses(result) == [GridStatus.ERROR] * 3


async def test_filling_tmp_runs_into_the_memory_limit(vora: Vora) -> None:
    result = await run(vora, "fill_tmp_past_memory")

    assert GridStatus.OK not in statuses(result), "2 GB went into /tmp under a 256 MiB limit"
    assert GridStatus.TIMEOUT not in statuses(result), "the per-input timeout ended it, so this shows nothing"
    assert result.run_status is RunStatus.KILLED_OOM
    if result.peak_mem_bytes is not None:
        assert result.peak_mem_bytes <= PROFILE.memory_bytes


@pytest.fixture
async def one_member(vora: Vora) -> AsyncIterator[Pool]:
    """With one member and one run at a time, the second run has to land on the first's sandbox."""
    pool = await vora.pools.declare(
        f"vora-arc-hostile-{secrets.token_hex(4)}", **pool_template(PROFILE), size=1, max_size=1
    )
    yield pool
    await pool.delete()


async def plant_then_look(pool: Pool, writer: str) -> tuple[BatchResult, BatchResult]:
    program = (HOSTILE / f"{writer}.py").read_text()
    looker = (HOSTILE / "find_hostile_files.py").read_text()
    planted = await pool_batch(pool, PROFILE, program, TASK, correlation_id=f"hostile/{writer}")
    assert statuses(planted) == [GridStatus.OK] * 3, "the write has to have worked for this to show anything"
    looked = await pool_batch(pool, PROFILE, looker, TASK, correlation_id=f"hostile/{writer}/look")
    assert looked.sandbox_id == planted.sandbox_id, "a different sandbox would be clean anyway"
    assert looked.warm_start is True
    return planted, looked


@pytest.mark.parametrize(("writer", "cell"), WRITERS.items())
async def test_a_write_does_not_survive_into_the_next_run(one_member: Pool, writer: str, cell: int) -> None:
    _, looked = await plant_then_look(one_member, writer)

    assert looked.grids[0].output is not None
    assert looked.grids[0].output[0][cell] == 0, f"run B on the same sandbox found what {writer} left"
    assert looked.reset_outcome == "POOL_RESET_OK"


@pytest.mark.skipif(
    not (os.environ.get("VORA_ADMIN_API_KEY") and os.environ.get("VORA_ARC_TENANT_ID")),
    reason="needs VORA_ADMIN_API_KEY, VORA_ARC_TENANT_ID and a runner with VORA_POOL_UNSAFE_REUSE=allow",
)
@pytest.mark.parametrize(("writer", "cell"), WRITERS.items())
async def test_without_a_reset_the_same_write_does_survive(vora: Vora, writer: str, cell: int) -> None:
    """The control: it shows the test above can find a leak, and why the reset exists."""
    name = f"vora-arc-hostile-unsafe-{secrets.token_hex(4)}"
    async with Vora(api_key=os.environ["VORA_ADMIN_API_KEY"]) as admin:
        await admin.pools.declare(
            name,
            **pool_template(PROFILE),
            size=1,
            max_size=1,
            reuse="unsafe_no_reset",
            tenant_id=os.environ["VORA_ARC_TENANT_ID"],
        )
    pool = await vora.pools.get(name)
    try:
        _, looked = await plant_then_look(pool, writer)
    finally:
        await pool.delete()

    assert looked.grids[0].output is not None
    assert looked.grids[0].output[0][cell] == 1
    assert looked.reset_outcome == "POOL_RESET_SKIPPED"


@pytest.mark.parametrize("name", ["print_100mb", "flood_fd1"])
async def test_printing_100mb_completes_with_a_4kb_tail(vora: Vora, name: str) -> None:
    result = await run(vora, name)

    assert result.run_status is RunStatus.COMPLETED
    assert statuses(result) == [GridStatus.OK] * 3
    assert len(result.stderr_tail.encode()) <= PROFILE.output_tail_bytes


async def test_environment_proc_and_mounts_hold_no_credentials(vora: Vora) -> None:
    result = await run(vora, "read_environment")

    assert result.run_status is RunStatus.COMPLETED
    assert statuses(result) == [GridStatus.OK] * 3
    report = json.loads(result.stderr_tail.strip().splitlines()[-1])
    # The python base image sets GPG_KEY to the public fingerprint that signs CPython releases.
    assert [name for name in report["secret_env"] if name != "GPG_KEY"] == [], report
    api_key_hash = hashlib.sha256(os.environ["VORA_API_KEY"].encode()).hexdigest()[:16]
    assert api_key_hash not in report["value_sha256"], report
    assert report["credential_paths"] == [], report


async def test_none_ragged_and_out_of_range_outputs_are_invalid(vora: Vora) -> None:
    result = await run(vora, "invalid_outputs")

    assert result.run_status is RunStatus.COMPLETED
    assert statuses(result) == [GridStatus.INVALID] * 3
