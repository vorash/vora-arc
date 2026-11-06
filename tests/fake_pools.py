"""vora-api's pool routes on a real socket, speaking the wire shape of `sdk/testdata/pool_wire.json`.

No program runs. `transform` stands in for the program, so a test can see that the runner's
stdin arrived and can give an answer that is right or wrong.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from collections import Counter, deque
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

Frame = dict[str, Any]

TENANT_KEY = "vora_tenant_test"
ADMIN_KEY = "vora_admin_test"


def reverse_rows(grid: list[list[int]]) -> list[list[int]]:
    return [row[::-1] for row in grid]


def stdout_frame(*lines: dict[str, Any]) -> Frame:
    data = "".join(json.dumps(line) + "\n" for line in lines).encode()
    return {"stdout": base64.b64encode(data).decode()}


@dataclass(frozen=True)
class Refuse:
    """The next run gets this status instead of a stream."""

    status: int
    error: str = "refused"
    retry_after: str | None = None
    state: str | None = None
    """What `GET` then answers, which is how the SDK tells one 409 from another."""


@dataclass(frozen=True)
class Frames:
    """The next run gets exactly these frames. `{"error": ...}` as the last is the API's failure line."""

    frames: tuple[Frame, ...]
    hold: bool = False
    """Then wait for the client to leave, as a run in progress does."""
    delay_s: float = 0.0
    """Wait this long before the first frame, as a slow run does."""


Script = Refuse | Frames


@dataclass
class Member:
    id: str
    runs: int = 0


@dataclass(frozen=True)
class Placement:
    member: Member
    warm: bool


@dataclass
class _Waiter:
    granted: threading.Event = field(default_factory=threading.Event)
    placement: Placement | None = None


@dataclass
class LivePool:
    """Vora's borrow rule and retirement (`internal/pool/pool.go`), minus the sandboxes: what warm and cold mean.

    A retired member keeps its slot until its destroy returns. A borrower with no idle member then
    waits, unless nothing is in flight and a slot is free, when it starts cold. When a destroy
    returns, the freed slot goes to the first waiter as a cold start if nothing else is in flight,
    and otherwise starts a replacement in the background.
    """

    size: int
    max_size: int
    max_runs: int | None
    no_reset: bool
    destroy_s: float = 0.0
    start_s: float = 0.0
    idle: deque[Member] = field(default_factory=deque)
    waiters: deque[_Waiter] = field(default_factory=deque)
    busy: int = 0
    starting: int = 0
    retiring: int = 0
    max_busy: int = 0
    started: int = 0
    retired: Counter[str] = field(default_factory=Counter)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        for _ in range(self.size):
            self.idle.append(self._new_member())

    @classmethod
    def from_spec(cls, spec: dict[str, Any], destroy_s: float = 0.0, start_s: float = 0.0) -> LivePool:
        size = int(spec.get("size", 8))
        return cls(
            size=size,
            max_size=int(spec.get("maxSize", max(size, 1))),
            max_runs=int(spec["maxRuns"]) if "maxRuns" in spec else None,
            no_reset=spec.get("reuse") == "POOL_REUSE_UNSAFE_NO_RESET",
            destroy_s=destroy_s,
            start_s=start_s,
        )

    def borrow(self) -> Placement:
        with self._lock:
            if self.idle:
                return self._lend(self.idle.popleft(), warm=True)
            if not self._in_flight() and self._slot_free():
                return self._lend(self._new_member(), warm=False)
            waiter = _Waiter()
            self.waiters.append(waiter)
        assert waiter.granted.wait(30), "no member came back for a waiting borrower"
        assert waiter.placement is not None
        return waiter.placement

    def check_in(self, member: Member) -> Frame:
        with self._lock:
            self.busy -= 1
            cause = "shrink" if self.size == 0 else "max_runs" if self.max_runs and member.runs >= self.max_runs else None
            if cause is not None:
                self.retired[cause] += 1
                self.retiring += 1
                threading.Thread(target=self._destroy, daemon=True).start()
                return {"outcome": "POOL_RESET_RETIRED", "retireCause": cause}
            self._to_idle(member)
        return {"outcome": "POOL_RESET_SKIPPED"} if self.no_reset else {"outcome": "POOL_RESET_OK", "resetMs": "3"}

    def _new_member(self) -> Member:
        self.started += 1
        return Member(f"sbx_{self.started}")

    def _lend(self, member: Member, warm: bool) -> Placement:
        member.runs += 1
        self.busy += 1
        self.max_busy = max(self.max_busy, self.busy)
        return Placement(member, warm)

    def _in_flight(self) -> bool:
        return self.starting > 0 or (self.size > 0 and self.busy > 0)

    def _slot_free(self) -> bool:
        return len(self.idle) + self.busy + self.starting + self.retiring < self.max_size

    def _grant(self, member: Member, warm: bool) -> None:
        waiter = self.waiters.popleft()
        waiter.placement = self._lend(member, warm)
        waiter.granted.set()

    def _to_idle(self, member: Member) -> None:
        if self.waiters:
            self._grant(member, warm=True)
        else:
            self.idle.append(member)

    def _destroy(self) -> None:
        time.sleep(self.destroy_s)
        with self._lock:
            self.retiring -= 1
            if self.waiters and not self._in_flight() and self._slot_free():
                self._grant(self._new_member(), warm=False)
                return
            while len(self.idle) + self.busy + self.starting < self.size and self._slot_free():
                self.starting += 1
                threading.Thread(target=self._start, daemon=True).start()

    def _start(self) -> None:
        time.sleep(self.start_s)
        with self._lock:
            self.starting -= 1
            self._to_idle(self._new_member())


@dataclass(frozen=True)
class Seen:
    method: str
    path: str
    query: str
    key: str | None
    body: dict[str, Any] | None


@dataclass
class FakePools:
    transform: Callable[[list[list[int]]], list[list[int]]] = reverse_rows
    runs: deque[Script] = field(default_factory=deque)
    """What the next runs get. Once empty, `script_for` decides."""
    script_for: Callable[[str, str], Script | None] = lambda pool, program: None
    """Given the pool's name and the program, what this run gets. None: it behaves as its pool's shape says."""
    seen: list[Seen] = field(default_factory=list)
    specs: dict[str, dict[str, Any]] = field(default_factory=dict)
    state: str = "POOL_ACTIVE"
    starting_polls: int = 0
    """How many `GET`s answer with no idle member yet."""
    declare_error: tuple[int, str] | None = None
    audit: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    runner_versions: list[str] = field(default_factory=lambda: ["0.10.9"])
    usage: dict[str, Any] = field(
        default_factory=lambda: {"cpuMillis": "21", "memoryPeakBytes": "9437184", "memoryPeakScope": "PEAK_SCOPE_WINDOW"}
    )
    in_flight: int = 0
    max_in_flight: int = 0
    client_left: threading.Event = field(default_factory=threading.Event)
    destroy_s: float = 0.0
    """How long a retired member holds its slot."""
    start_s: float = 0.0
    """How long a replacement member takes to start."""
    live: dict[str, LivePool] = field(default_factory=dict)
    """Each pool's members, from its first run."""
    _executions: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def calls(self, method: str, suffix: str = "") -> list[Seen]:
        return [call for call in self.seen if call.method == method and call.path.endswith(suffix)]

    @contextmanager
    def running(self) -> Iterator[FakePools]:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        thread = threading.Thread(target=self._server.serve_forever, args=(0.01,), daemon=True)
        thread.start()
        try:
            yield self
        finally:
            self._server.shutdown()
            self._server.server_close()
            thread.join()

    def live_pool(self, name: str) -> LivePool:
        with self._lock:
            return self.live.setdefault(name, LivePool.from_spec(self.specs.get(name, {}), self.destroy_s, self.start_s))

    def run_frames(self, spec: dict[str, Any], stdin: dict[str, Any], placement: Placement) -> list[Frame]:
        """Everything before `runDone`, which comes once the member is checked in."""
        results = [
            {"index": item["index"], "status": "OK", "output": self.transform(item["grid"]), "error": None, "wall_ms": 1}
            for item in stdin["inputs"]
        ]
        output = stdout_frame(*results, {"done": True, "stderr_tail": ""})
        with self._lock:
            self._executions += 1
            execution = f"exe_{self._executions}"
        exit_ = {"reason": "EXITED", "executionId": execution, "usage": self.usage}
        run: Frame = {"poolId": "pool_test", "sandboxId": placement.member.id, "executionId": execution}
        run["sandboxRun"] = placement.member.runs
        if spec.get("reuse") == "POOL_REUSE_UNSAFE_NO_RESET":
            run["reuse"] = "POOL_REUSE_UNSAFE_NO_RESET"
        else:
            run["reuse"] = "POOL_REUSE_RESET"
        if not placement.warm:
            run["startupMs"] = "185"
        elif spec.get("reuse") == "POOL_REUSE_UNSAFE_NO_RESET":
            run["warm"] = True
        else:
            run |= {"warm": True, "startupMs": "1"}
            if placement.member.runs > 1:
                run["resetMs"] = "7"
        return [{"run": run}, output, {"exit": exit_}]

    def _info(self, name: str) -> dict[str, Any]:
        spec = self.specs.get(name, {"name": name})
        info: dict[str, Any] = {"id": f"pool_{name}", "spec": spec, "state": self.state}
        if self.state in ("POOL_ACTIVE", "POOL_DRAINING"):
            starting = self.starting_polls > 0
            self.starting_polls = max(self.starting_polls - 1, 0)
            info["stats"] = {"idle": 0 if starting else spec.get("size", 8), "starting": 1 if starting else 0}
        return info

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def _seen(self) -> tuple[list[str], dict[str, Any] | None]:
                url = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                authorization = self.headers.get("Authorization") or ""
                call = Seen(self.command, url.path, url.query, authorization.removeprefix("Bearer "), body)
                with fake._lock:
                    fake.seen.append(call)
                return url.path.strip("/").split("/"), body

            def _reply(self, status: int, payload: Any, retry_after: str | None = None) -> None:
                data = json.dumps(payload).encode() if payload is not None else b""
                self.send_response(status)
                if retry_after is not None:
                    self.send_header("Retry-After", retry_after)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_PUT(self) -> None:
                parts, body = self._seen()
                assert body is not None
                if fake.declare_error is not None:
                    status, error = fake.declare_error
                    self._reply(status, {"error": error})
                    return
                fake.specs[parts[2]] = body
                self._reply(200, fake._info(parts[2]))

            def do_GET(self) -> None:
                parts, _ = self._seen()
                if parts == ["v1", "runners"]:
                    key = self.headers.get("Authorization") or ""
                    if key != f"Bearer {ADMIN_KEY}":
                        self._reply(403, {"error": "runner inventory requires a global administrator"})
                        return
                    self._reply(200, {"runners": [{"id": "r1", "version": v} for v in fake.runner_versions]})
                elif parts[-1] == "execs":
                    self._reply(200, {"execs": fake.audit.get(parts[4], [])})
                else:
                    self._reply(200, fake._info(parts[2]))

            def do_DELETE(self) -> None:
                self._seen()
                self._reply(204, None)

            def _frames(self, frames: Iterable[Frame]) -> None:
                for frame in frames:
                    self.wfile.write(json.dumps(frame).encode() + b"\n")
                    self.wfile.flush()

            def do_POST(self) -> None:
                parts, body = self._seen()
                assert body is not None
                stdin = json.loads(base64.b64decode(body["stdin"])) if "stdin" in body else {}
                with fake._lock:
                    script = fake.runs.popleft() if fake.runs else None
                    if script is None and "program" in stdin:
                        script = fake.script_for(parts[2], stdin["program"])
                    fake.in_flight += 1
                    fake.max_in_flight = max(fake.max_in_flight, fake.in_flight)
                try:
                    if isinstance(script, Refuse):
                        if script.state is not None:
                            fake.state = script.state
                        self._reply(script.status, {"error": script.error}, script.retry_after)
                        return
                    if isinstance(script, Frames):
                        time.sleep(script.delay_s)
                    pool = fake.live_pool(parts[2]) if script is None else None
                    placement = pool.borrow() if pool else None
                    frames = script.frames if script else fake.run_frames(fake.specs.get(parts[2], {}), stdin, placement)  # type: ignore[arg-type]
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.end_headers()
                    self._frames(frames)
                    if pool and placement:
                        self._frames([{"runDone": pool.check_in(placement.member)}])
                    if isinstance(script, Frames) and script.hold:
                        self.connection.recv(1)
                        fake.client_left.set()
                finally:
                    with fake._lock:
                        fake.in_flight -= 1

        return Handler
