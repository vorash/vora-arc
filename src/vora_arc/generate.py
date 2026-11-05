"""Ask an OpenAI-compatible model for candidate programs, paying for each sample once."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .model import Grid, Task, redact_userinfo, storable_text

log = logging.getLogger(__name__)

TEMPERATURE = 0.8
MAX_TOKENS = 4096
MAX_SAMPLES_PER_REQUEST = 16
RETRY_DELAYS_S: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)
REQUEST_TIMEOUT_S = 600.0

_RETRYABLE_STATUS = {408, 409, 425, 429}
_PYTHON_FENCES = {"", "python", "python3", "py"}
_FENCE = re.compile(r"^[ \t]*```[ \t]*([\w+-]*)[ \t]*\r?\n(.*?)^[ \t]*```[ \t]*$", re.MULTILINE | re.DOTALL)
_TRANSFORM = re.compile(r"\bdef\s+transform\s*\(")


class ModelError(Exception):
    """The model endpoint would not produce completions, even after retries."""


class _TransientResponse(Exception):
    pass


@dataclass(frozen=True)
class ModelConfig:
    url: str
    model: str
    temperature: float = TEMPERATURE
    max_tokens: int = MAX_TOKENS
    auth: tuple[str, str] | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> ModelConfig:
        missing = [name for name in ("VLLM_URL", "VLLM_MODEL") if not os.environ.get(name)]
        if missing:
            raise SystemExit(f"set {' and '.join(missing)}: VLLM_URL is the API base, e.g. http://gpu:8000/v1")
        url, auth = _split_credentials(os.environ["VLLM_URL"])
        return cls(url=url, model=os.environ["VLLM_MODEL"], auth=auth)


def _split_credentials(raw: str) -> tuple[str, tuple[str, str] | None]:
    """Separate a URL's credentials from it. httpx logs and raises the URL it was given, password included."""
    try:
        url = httpx.URL(raw)
    except httpx.InvalidURL:
        # The parser's message can quote the password, as in "Invalid port: 'secret'".
        raise SystemExit("VLLM_URL is not a valid URL") from None
    if url.scheme not in ("http", "https") or not url.host:
        raise SystemExit("VLLM_URL must be an http or https URL with a host")
    if not url.userinfo:
        return raw, None
    return str(url.copy_with(username=None, password=None)), (url.username, url.password)


class CompletionCache(Protocol):
    async def load_completions(self, task_id: str, prompt_hash: str) -> Mapping[int, str]: ...

    async def save_completions(self, task_id: str, prompt_hash: str, model: str, texts: Mapping[int, str]) -> None: ...


@dataclass(frozen=True)
class Sampled:
    prompt_hash: str
    texts: tuple[str, ...]
    """One completion per sample index, 0 to n-1."""
    fresh: int
    cached: int
    request_ms: int | None
    """Wall-clock time with a request open; None when the cache answered everything."""


def render_grid(grid: Grid) -> str:
    return "\n".join(" ".join(str(cell) for cell in row) for row in grid)


def task_prompt(task: Task) -> str:
    """The task as the model sees it. Test outputs are the answer, so they never appear."""
    parts = [
        "This is an ARC-AGI puzzle. A grid is a rectangle of integers 0 to 9, written below as rows of "
        "digits separated by spaces. One hidden rule turns every input grid into its output grid.",
    ]
    for number, pair in enumerate(task.train, start=1):
        parts.append(f"Example {number} input:\n{render_grid(pair.input)}")
        parts.append(f"Example {number} output:\n{render_grid(pair.output)}")
    for number, case in enumerate(task.test, start=1):
        parts.append(f"Test input {number}:\n{render_grid(case.input)}")
    return "\n\n".join(parts)


def ask_for_program(prompt: str) -> str:
    return (
        f"{prompt}\n\nWrite one Python function that applies the rule to any input grid:\n\n"
        "def transform(grid: list[list[int]]) -> list[list[int]]\n\n"
        "Use only the standard library and numpy. Reply with the function in one fenced ```python block."
    )


def prompt_hash(config: ModelConfig, prompt: str) -> str:
    """The cache key's prompt part. A different model or sampling setting is a different sample."""
    identity = {
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "prompt": prompt,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()


def extract_program(text: str) -> str | None:
    """The first fenced Python block defining `transform`. A bare fence counts as Python."""
    for language, body in _FENCE.findall(text):
        if language.lower() in _PYTHON_FENCES and _TRANSFORM.search(body):
            return str(body)
    return None


async def sample(
    http: httpx.AsyncClient,
    config: ModelConfig,
    cache: CompletionCache,
    task_id: str,
    prompt: str,
    n: int,
) -> Sampled:
    """Return completions 0 to n-1, requesting only the ones the cache doesn't hold.

    Each response is cached before the next request, so a crash loses at most one request.
    """
    key = prompt_hash(config, prompt)
    held = {index: text for index, text in (await cache.load_completions(task_id, key)).items() if index < n}
    cached = len(held)
    request_ms: int | None = None
    while missing := [index for index in range(n) if index not in held]:
        texts, elapsed_ms = await _request(http, config, prompt, min(len(missing), MAX_SAMPLES_PER_REQUEST))
        request_ms = (request_ms or 0) + elapsed_ms
        fresh = dict(zip(missing, texts))
        await cache.save_completions(task_id, key, config.model, fresh)
        held.update(fresh)
    return Sampled(key, tuple(held[index] for index in range(n)), n - cached, cached, request_ms)


async def _request(http: httpx.AsyncClient, config: ModelConfig, prompt: str, n: int) -> tuple[list[str], int]:
    body = {
        "model": config.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "n": n,
    }
    url = f"{config.url.rstrip('/')}/chat/completions"
    auth = httpx.BasicAuth(*config.auth) if config.auth else httpx.USE_CLIENT_DEFAULT
    delays = iter(RETRY_DELAYS_S)
    elapsed_ms = 0
    while True:
        started = time.monotonic()
        try:
            texts = _completions(await http.post(url, json=body, auth=auth))
            return texts[:n], elapsed_ms + _elapsed_ms(started)
        except (httpx.TransportError, _TransientResponse) as error:
            problem = f"{type(error).__name__}: {error}"
        elapsed_ms += _elapsed_ms(started)
        delay = next(delays, None)
        if delay is None:
            raise ModelError(f"{url}: gave up after {len(RETRY_DELAYS_S) + 1} attempts: {problem}")
        log.warning("%s: %s; retrying in %ss", url, problem, delay)
        await asyncio.sleep(delay)


def _completions(response: httpx.Response) -> list[str]:
    status = response.status_code
    if status >= 500 or status in _RETRYABLE_STATUS:
        raise _TransientResponse(f"HTTP {status}")
    if status != 200:
        # The body can be a proxy's HTML error page, and can quote the URL it was asked for.
        body = " ".join(redact_userinfo(response.text).split())[:500]
        raise ModelError(f"{response.url}: HTTP {status}: {body}")
    try:
        texts: list[Any] = [choice["message"]["content"] for choice in response.json()["choices"]]
    except (ValueError, KeyError, TypeError) as error:
        raise _TransientResponse(f"malformed completion response: {error!r}") from error
    if not texts or not all(isinstance(text, str) for text in texts):
        raise _TransientResponse("completion response has no choices, or a choice has no text")
    return [storable_text(text) for text in texts]


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
