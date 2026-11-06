"""A local OpenAI-compatible server with canned completions, for runs with no model or GPU."""

from __future__ import annotations

import json
import threading
import time
from collections import Counter, deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def fenced(program: str) -> str:
    return f"Here is the function.\n\n```python\n{program}```\n"


class DictCache:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, int], str] = {}

    async def load_completions(self, task_id: str, prompt_hash: str) -> dict[int, str]:
        return {i: text for (t, p, i), text in self.rows.items() if (t, p) == (task_id, prompt_hash)}

    async def save_completions(self, task_id: str, prompt_hash: str, model: str, texts: Mapping[int, str]) -> dict[int, str]:
        return {i: self.rows.setdefault((task_id, prompt_hash, i), text) for i, text in texts.items()}


class FakeModel:
    """`canned(prompt)` gives the completions for a prompt, served in order and cycled.

    `faults` queues what the next requests get instead of completions: an HTTP
    status, a (status, body) pair, "drop" to close the connection, or "garbage" for
    a 200 that isn't JSON.
    """

    def __init__(self, canned: Callable[[str], Sequence[str]]) -> None:
        self.canned = canned
        self.requests: list[dict[str, Any]] = []
        self.faults: deque[int | str | tuple[int, str]] = deque()
        self.max_choices_per_response: int | None = None
        self.delay_s = 0.0
        self.peak_open_requests = 0
        self._open_requests = 0
        self._served: Counter[str] = Counter()
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    @property
    def completions_served(self) -> int:
        return sum(self._served.values())

    @contextmanager
    def running(self) -> Iterator[FakeModel]:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        thread = threading.Thread(target=self._server.serve_forever, args=(0.01,), daemon=True)
        thread.start()
        try:
            yield self
        finally:
            self._server.shutdown()
            self._server.server_close()
            thread.join()

    def _next_choices(self, prompt: str, n: int) -> list[str]:
        canned = self.canned(prompt)
        with self._lock:
            start = self._served[prompt]
            if self.max_choices_per_response is not None:
                n = min(n, self.max_choices_per_response)
            self._served[prompt] += n
        return [canned[(start + offset) % len(canned)] for offset in range(n)]

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with fake._lock:
                    fake.requests.append({"path": self.path, "authorization": self.headers.get("Authorization"), **body})
                    fault = fake.faults.popleft() if fake.faults else None
                    fake._open_requests += 1
                    fake.peak_open_requests = max(fake.peak_open_requests, fake._open_requests)
                time.sleep(fake.delay_s)
                with fake._lock:
                    fake._open_requests -= 1
                if fault == "drop":
                    self.connection.close()
                elif fault == "garbage":
                    self._reply(200, b"<html>not json</html>")
                elif isinstance(fault, tuple):
                    self._reply(fault[0], fault[1].encode())
                elif isinstance(fault, int):
                    self._reply(fault, b'{"error": "injected"}')
                else:
                    prompt = body["messages"][-1]["content"]
                    choices = [
                        {"index": i, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
                        for i, text in enumerate(fake._next_choices(prompt, body["n"]))
                    ]
                    self._reply(200, json.dumps({"object": "chat.completion", "choices": choices}).encode())

            def _reply(self, status: int, payload: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        return Handler
