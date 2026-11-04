"""run_batch against a fake vora-api: what the client sends, and how it reads every way a run ends."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from vora import Vora, VoraError

from vora_arc import client
from vora_arc.client import SandboxInfrastructureError, run_batch
from vora_arc import model
from vora_arc.model import GridStatus, Pair, RunStatus, Task
from vora_arc.profile import DEFAULT_PROFILE_PATH, load_profile

PROFILE = load_profile(DEFAULT_PROFILE_PATH)
PROGRAM = "def transform(grid):\n    return [row[::-1] for row in grid]\n"
TASK = Task(
    id="t1",
    train=(Pair(((1, 2),), ((2, 1),)), Pair(((3, 4),), ((4, 3),))),
    test=(model.TestCase(((5, 6),), None),),
)


def stdout(*lines: dict[str, Any]) -> dict[str, Any]:
    data = "".join(json.dumps(line) + "\n" for line in lines).encode()
    return {"stdout": base64.b64encode(data).decode()}


def raw_stdout(data: bytes) -> dict[str, Any]:
    return {"stdout": base64.b64encode(data).decode()}


def ok(index: int, output: list[list[int]]) -> dict[str, Any]:
    return {"index": index, "status": "OK", "output": output, "error": None, "wall_ms": 3}


def failed(index: int, status: str, error: str) -> dict[str, Any]:
    return {"index": index, "status": status, "output": None, "error": error, "wall_ms": 5}


def done(tail: str = "") -> dict[str, Any]:
    return {"done": True, "stderr_tail": tail}


def exit_(reason: str | None) -> dict[str, Any]:
    return {"exit": {"reason": reason} if reason else {}}


ALL_OK = [stdout(ok(0, [[2, 1]]), ok(1, [[4, 3]]), ok(2, [[6, 5]]), done("printed\n")), exit_("EXITED")]


@dataclass
class FakeVora:
    """A vora-api stand-in. ``broken`` maps an operation to how many calls fail at the transport."""

    exec_chunks: list[dict[str, Any]] = field(default_factory=lambda: list(ALL_OK))
    stats: dict[str, Any] = field(default_factory=lambda: {"memoryPeakBytes": "52428800", "cpuMillis": "120"})
    broken: dict[str, int] = field(default_factory=dict)
    break_exec_stream_after_output: bool = False
    destroy_status: int = 204
    calls: list[tuple[str, str]] = field(default_factory=list)
    bodies: dict[str, Any] = field(default_factory=dict)

    def count(self, op: str) -> int:
        return sum(1 for name, _ in self.calls if name == op)

    def destroyed(self) -> list[str]:
        return [sandbox for name, sandbox in self.calls if name == "destroy"]

    def created(self) -> list[str]:
        return [sandbox for name, sandbox in self.calls if name == "create"]

    def route(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")
        if request.method == "POST" and len(parts) == 2:
            op, sandbox = "create", f"sbx_{self.count('create') + 1}"
        else:
            sandbox = parts[2]
            op = {"POST": "exec", "GET": "stats", "DELETE": "destroy"}[request.method]
        self.calls.append((op, sandbox))
        if self.broken.get(op, 0) > 0:
            self.broken[op] -= 1
            raise httpx.ConnectError("connection refused", request=request)
        if request.content:
            self.bodies[op] = json.loads(request.content)
        if op == "create":
            return httpx.Response(201, json={"id": sandbox, "state": "RUNNING"})
        if op == "exec":
            body = "".join(json.dumps(chunk) + "\n" for chunk in self.exec_chunks).encode()
            if self.break_exec_stream_after_output:
                return httpx.Response(200, content=_then_break(body, request))
            return httpx.Response(200, headers={"content-type": "application/x-ndjson"}, content=body)
        if op == "stats":
            return httpx.Response(200, json=self.stats)
        return httpx.Response(self.destroy_status, json={"error": "boom"} if self.destroy_status >= 400 else None)


async def _then_break(body: bytes, request: httpx.Request) -> AsyncIterator[bytes]:
    yield body
    raise httpx.ReadError("connection reset", request=request)


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "RETRY_DELAYS_S", (0.0, 0.0, 0.0))


async def run(fake: FakeVora, program: str = PROGRAM) -> Any:
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake.route)) as http:
        vora = Vora(base_url="http://vora.test", api_key="vora_test", client=http)
        return await run_batch(vora, PROFILE, program, TASK, correlation_id="t1/c1")


def test_shipped_profile_holds_the_spec_v2_limits() -> None:
    # Spec section 3, V2: these are the limits every candidate runs under.
    assert (PROFILE.backend, PROFILE.network) == ("gvisor", "none")
    # pids is 64, not the spec's 16: under gVisor the limit also counts runsc's own threads.
    assert (PROFILE.cpu_millis, PROFILE.memory_bytes, PROFILE.pids) == (1000, 256 * 1024 * 1024, 64)
    assert (PROFILE.per_input_timeout_ms, PROFILE.batch_timeout_seconds) == (2000, 10)
    assert PROFILE.output_tail_bytes == 4096


async def test_sandbox_is_created_with_the_profile_limits_and_fed_the_protocol_on_stdin() -> None:
    fake = FakeVora()
    await run(fake)

    create = fake.bodies["create"]
    assert create["image"] == PROFILE.image
    assert create["backend"] == "gvisor"
    assert create["network"] == {"mode": "NETWORK_NONE"}
    assert create["resources"] == {"cpuMillis": "1000", "memoryBytes": str(256 * 1024 * 1024), "pids": "64"}
    # The TTL removes a sandbox whose destroy call failed.
    assert create["ttlSeconds"] == str(PROFILE.ttl_seconds)

    exec_ = fake.bodies["exec"]
    assert [exec_["command"], *exec_["args"]] == list(PROFILE.runner_command)
    assert exec_["timeoutSeconds"] == "10"
    assert json.loads(base64.b64decode(exec_["stdin"])) == {
        "program": PROGRAM,
        "inputs": [
            {"index": 0, "is_test": False, "grid": [[1, 2]]},
            {"index": 1, "is_test": False, "grid": [[3, 4]]},
            {"index": 2, "is_test": True, "grid": [[5, 6]]},
        ],
        "per_input_timeout_ms": 2000,
    }


async def test_full_batch_reports_every_input_with_its_output_and_the_run_facts() -> None:
    fake = FakeVora()
    result = await run(fake)

    assert result.run_status is RunStatus.COMPLETED
    assert [(g.index, g.is_test, g.status, g.output) for g in result.grids] == [
        (0, False, GridStatus.OK, ((2, 1),)),
        (1, False, GridStatus.OK, ((4, 3),)),
        (2, True, GridStatus.OK, ((6, 5),)),
    ]
    assert result.correlation_id == "t1/c1"
    assert result.program_sha256 == hashlib.sha256(PROGRAM.encode()).hexdigest()
    assert result.sandbox_id == "sbx_1"
    assert (result.peak_mem_bytes, result.cpu_ms) == (52428800, 120)
    assert result.stderr_tail == "printed\n"
    assert result.startup_ms >= 0 and result.exec_ms >= 0
    assert fake.destroyed() == ["sbx_1"]


async def test_result_line_split_across_stream_chunks_is_reassembled() -> None:
    line = (json.dumps(ok(0, [[2, 1]])) + "\n").encode()
    rest = "".join(json.dumps(x) + "\n" for x in (ok(1, [[4, 3]]), ok(2, [[6, 5]]), done())).encode()
    fake = FakeVora(exec_chunks=[raw_stdout(line[:10]), raw_stdout(line[10:] + rest), exit_("EXITED")])

    result = await run(fake)

    assert [g.status for g in result.grids] == [GridStatus.OK] * 3


async def test_batch_timeout_mid_batch_keeps_finished_results_and_times_out_the_rest() -> None:
    # The verifier must still see input 0's real result after Vora kills the batch.
    fake = FakeVora(exec_chunks=[stdout(ok(0, [[2, 1]])), exit_("TIMEOUT_EXCEEDED")])

    result = await run(fake)

    assert result.run_status is RunStatus.KILLED_TIMEOUT
    assert [(g.status, g.output) for g in result.grids] == [
        (GridStatus.OK, ((2, 1),)),
        (GridStatus.TIMEOUT, None),
        (GridStatus.TIMEOUT, None),
    ]
    assert [g.is_test for g in result.grids] == [False, False, True]


async def test_oom_that_drops_the_exec_stream_keeps_finished_results() -> None:
    # Vora: an OOM often kills the sandbox init too, so the stream ends with no exit record.
    fake = FakeVora(
        exec_chunks=[stdout(ok(0, [[2, 1]]), failed(1, "ERROR", "MemoryError"))],
        stats={"oomKills": "1", "memoryPeakBytes": str(256 * 1024 * 1024)},
    )

    result = await run(fake)

    assert result.run_status is RunStatus.KILLED_OOM
    assert [g.status for g in result.grids] == [GridStatus.OK, GridStatus.ERROR, GridStatus.ERROR]
    assert result.grids[2].error is not None and "KILLED_OOM" in result.grids[2].error
    assert result.peak_mem_bytes == 256 * 1024 * 1024


@pytest.mark.parametrize(
    ("reason", "stats", "expected"),
    [
        ("EXITED", {}, RunStatus.COMPLETED),
        ("TIMEOUT_EXCEEDED", {}, RunStatus.KILLED_TIMEOUT),
        ("OOM_KILLED", {}, RunStatus.KILLED_OOM),
        ("PIDS_LIMIT_EXCEEDED", {}, RunStatus.POLICY_VIOLATION),
        # Vora's exit record says EXITED even when the cgroup killed or capped the run.
        ("EXITED", {"oomKills": "1"}, RunStatus.KILLED_OOM),
        ("EXITED", {"pidsLimitHits": "3"}, RunStatus.POLICY_VIOLATION),
    ],
)
async def test_exit_reason_maps_to_run_status(reason: str, stats: dict[str, str], expected: RunStatus) -> None:
    fake = FakeVora(exec_chunks=[*ALL_OK[:-1], exit_(reason)], stats=stats)

    result = await run(fake)

    assert result.run_status is expected


@pytest.mark.parametrize("reason", ["RUNTIME_FAILURE", "DISK_QUOTA_EXCEEDED", "POLICY_VIOLATION", "SOMETHING_NEW", None])
async def test_unknown_exit_reason_is_an_infrastructure_error_not_a_program_verdict(reason: str | None) -> None:
    # A wrong runner path shows up as RUNTIME_FAILURE; the error must carry Vora's stderr to say so.
    message = base64.b64encode(b"vora-init: exec: no such file or directory\n").decode()
    fake = FakeVora(exec_chunks=[*ALL_OK[:-1], {"stderr": message}, exit_(reason)])

    with pytest.raises(SandboxInfrastructureError, match="no such file or directory"):
        await run(fake)

    assert fake.count("exec") == 1
    assert fake.destroyed() == ["sbx_1"]


async def test_stream_without_exit_record_and_no_resource_kill_is_an_infrastructure_error() -> None:
    fake = FakeVora(exec_chunks=[stdout(ok(0, [[2, 1]]))])

    with pytest.raises(SandboxInfrastructureError):
        await run(fake)

    assert fake.destroyed() == ["sbx_1"]


async def test_transport_errors_on_create_are_retried() -> None:
    fake = FakeVora(broken={"create": 2})

    result = await run(fake)

    assert result.run_status is RunStatus.COMPLETED
    assert fake.count("create") == 3


async def test_transport_errors_give_up_after_three_retries() -> None:
    fake = FakeVora(broken={"create": 10})

    with pytest.raises(VoraError):
        await run(fake)

    assert fake.count("create") == 4


async def test_exec_that_never_connects_is_retried_in_a_fresh_sandbox() -> None:
    fake = FakeVora(broken={"exec": 1})

    result = await run(fake)

    assert result.sandbox_id == "sbx_2"
    assert fake.destroyed() == ["sbx_1", "sbx_2"]


async def test_program_failure_is_reported_not_retried() -> None:
    errors = [failed(i, "ERROR", "NameError: name 'transfrom' is not defined") for i in range(3)]
    fake = FakeVora(exec_chunks=[stdout(*errors, done()), exit_("EXITED")])

    result = await run(fake)

    assert result.run_status is RunStatus.COMPLETED
    assert [g.status for g in result.grids] == [GridStatus.ERROR] * 3
    assert fake.count("exec") == 1


async def test_stream_that_breaks_after_the_program_ran_is_not_retried() -> None:
    # The program already ran; running it again would retry a program, not a request.
    fake = FakeVora(exec_chunks=[stdout(ok(0, [[2, 1]]))], break_exec_stream_after_output=True)

    with pytest.raises(SandboxInfrastructureError):
        await run(fake)

    assert fake.count("exec") == 1
    assert fake.destroyed() == ["sbx_1"]


async def test_sandbox_is_destroyed_when_stats_fail() -> None:
    fake = FakeVora(broken={"stats": 1})

    with pytest.raises(SandboxInfrastructureError):
        await run(fake)

    assert fake.destroyed() == ["sbx_1"]


async def test_failed_destroy_does_not_hide_the_result() -> None:
    fake = FakeVora(destroy_status=500)

    result = await run(fake)

    assert result.run_status is RunStatus.COMPLETED
    assert fake.destroyed() == ["sbx_1"]


async def test_lines_that_are_not_protocol_results_are_ignored() -> None:
    # A program that writes to fd 1 must not be able to inject or corrupt results.
    fake = FakeVora(
        exec_chunks=[
            raw_stdout(b"hello from transform\n[1, 2]\n"),
            stdout({**ok(1, [[4, 3]]), "pad": "x" * client.MAX_LINE_BYTES}),
            stdout(ok(0, [[2, 1]]), ok(7, [[9]]), {"index": 1, "status": "OK", "output": None, "error": None, "wall_ms": 1}),
            stdout(ok(0, [[0]]), done()),
            exit_("EXITED"),
        ]
    )

    result = await run(fake)

    assert [(g.status, g.output) for g in result.grids] == [
        (GridStatus.OK, ((2, 1),)),
        (GridStatus.ERROR, None),
        (GridStatus.ERROR, None),
    ]


async def test_runner_stderr_is_cut_to_the_output_tail_when_the_done_line_is_missing() -> None:
    noise = b"a" * 10_000 + b"Traceback: the end"
    fake = FakeVora(exec_chunks=[{"stderr": base64.b64encode(noise).decode()}, exit_("EXITED")])

    result = await run(fake)

    assert len(result.stderr_tail.encode()) == PROFILE.output_tail_bytes
    assert result.stderr_tail.endswith("Traceback: the end")
    assert [g.status for g in result.grids] == [GridStatus.ERROR] * 3


@dataclass
class RunnerBackedVora(FakeVora):
    """Answers exec by running the real sandbox/runner.py on the stdin the client sent."""

    def route(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/exec"):
            stdin = base64.b64decode(json.loads(request.content)["stdin"])
            runner = Path(__file__).resolve().parents[1] / "sandbox" / "runner.py"
            proc = subprocess.run([sys.executable, str(runner)], input=stdin, capture_output=True, timeout=30, check=True)
            self.exec_chunks = [raw_stdout(proc.stdout), exit_("EXITED")]
        return super().route(request)


async def test_client_reads_what_the_real_runner_writes() -> None:
    # The runner and the client were written against PROTOCOL.md separately;
    # this is the only host test where one consumes the other's actual bytes.
    program = PROGRAM + "\nprint('hello from the program')\n"
    result = await run(RunnerBackedVora(), program)

    assert result.run_status is RunStatus.COMPLETED
    assert [(g.index, g.is_test, g.status, g.output) for g in result.grids] == [
        (0, False, GridStatus.OK, ((2, 1),)),
        (1, False, GridStatus.OK, ((4, 3),)),
        (2, True, GridStatus.OK, ((6, 5),)),
    ]
    assert "hello from the program" in result.stderr_tail
