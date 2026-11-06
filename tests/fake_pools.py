"""vora-api's pool routes on a real socket, speaking the wire shape of `sdk/testdata/pool_wire.json`.

No program runs. `transform` stands in for the program, so a test can see that the runner's
stdin arrived and can give an answer that is right or wrong.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
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
    _member_runs: int = 0
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

    def default_frames(self, spec: dict[str, Any], stdin: dict[str, Any]) -> list[Frame]:
        results = [
            {"index": item["index"], "status": "OK", "output": self.transform(item["grid"]), "error": None, "wall_ms": 1}
            for item in stdin["inputs"]
        ]
        output = stdout_frame(*results, {"done": True, "stderr_tail": ""})
        exit_ = {"reason": "EXITED", "executionId": f"exe_{self._member_runs}", "usage": self.usage}
        ids = {"poolId": "pool_test", "sandboxId": "sbx_1", "executionId": f"exe_{self._member_runs}"}
        if spec.get("size", 8) == 0:
            run = ids | {"startupMs": "185", "sandboxRun": 1, "reuse": "POOL_REUSE_RESET"}
            done = {"outcome": "POOL_RESET_RETIRED", "retireCause": "shrink"}
        elif spec.get("reuse") == "POOL_REUSE_UNSAFE_NO_RESET":
            run = ids | {"warm": True, "sandboxRun": self._member_runs, "reuse": "POOL_REUSE_UNSAFE_NO_RESET"}
            done = {"outcome": "POOL_RESET_SKIPPED"}
        else:
            run = ids | {"warm": True, "startupMs": "1", "sandboxRun": self._member_runs, "reuse": "POOL_REUSE_RESET"}
            if self._member_runs > 1:
                run["resetMs"] = "7"
            done = {"outcome": "POOL_RESET_OK", "resetMs": "3"}
        return [{"run": run}, output, {"exit": exit_}, {"runDone": done}]

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
                    fake._member_runs += 1
                try:
                    if isinstance(script, Refuse):
                        if script.state is not None:
                            fake.state = script.state
                        self._reply(script.status, {"error": script.error}, script.retry_after)
                        return
                    if isinstance(script, Frames):
                        time.sleep(script.delay_s)
                    frames = script.frames if script else fake.default_frames(fake.specs.get(parts[2], {}), stdin)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.end_headers()
                    for frame in frames:
                        self.wfile.write(json.dumps(frame).encode() + b"\n")
                        self.wfile.flush()
                    if isinstance(script, Frames) and script.hold:
                        self.connection.recv(1)
                        fake.client_left.set()
                finally:
                    with fake._lock:
                        fake.in_flight -= 1

        return Handler
