"""Spec section 5: each hostile program in tests/hostile/ runs in a real Vora sandbox and is contained.

These programs are never run on the host. Every test needs VORA_API_URL and VORA_API_KEY.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from vora import Vora

from vora_arc import model
from vora_arc.client import connect, run_batch
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
M2_WRITABLE = "M2: Vora cannot make the root filesystem read-only outside /tmp yet"

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


async def test_fork_bomb_is_a_policy_violation(vora: Vora) -> None:
    result = await run(vora, "fork_bomb")

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
        pytest.param("write_workspace", marks=pytest.mark.xfail(strict=True, reason=M2_WRITABLE)),
        pytest.param("write_root_home", marks=pytest.mark.xfail(strict=True, reason=M2_WRITABLE)),
    ],
)
async def test_writing_outside_tmp_fails(vora: Vora, name: str) -> None:
    result = await run(vora, name)

    assert result.run_status is RunStatus.COMPLETED
    assert statuses(result) == [GridStatus.ERROR] * 3


@pytest.mark.xfail(strict=True, reason="M2: Vora cannot mount a 16 MB tmpfs at /tmp yet")
async def test_filling_tmp_past_16mb_fails(vora: Vora) -> None:
    result = await run(vora, "fill_tmp")

    assert statuses(result) == [GridStatus.ERROR] * 3


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
