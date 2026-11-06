"""The prompt, program extraction, and the rule that a sample is paid for once.

Every request crosses real HTTP to tests/fake_model.py. The cache here is a dict;
tests/test_store.py covers the same interface on PostgreSQL.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from fake_model import DictCache, FakeModel, fenced

from vora_arc import generate, model
from vora_arc.generate import (
    ModelConfig,
    ModelError,
    ask_for_program,
    extract_program,
    prompt_hash,
    sample,
    task_prompt,
)
from vora_arc.model import Pair, Task

TASK = Task(
    id="t1",
    train=(Pair(((1, 2), (3, 4)), ((4, 3), (2, 1))),),
    test=(model.TestCase(((5, 6),), ((6, 5),)), model.TestCase(((7, 7),), ((9, 9),))),
)
PROGRAM = "def transform(grid):\n    return grid\n"



@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeModel]:
    monkeypatch.setattr(generate, "RETRY_DELAYS_S", (0.0, 0.0, 0.0))
    server = FakeModel(lambda prompt: [f"completion {i}" for i in range(1000)])
    with server.running():
        yield server


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        yield client


def config(fake: FakeModel, name: str = "m1") -> ModelConfig:
    return ModelConfig(url=fake.url, model=name)


@pytest.mark.parametrize(
    "bad",
    ["http://user:secret", "http://user:secret@host:abc/v1", "user:secret@host/v1"],
    ids=["password-read-as-port", "bad-port", "no-scheme"],
)
def test_a_bad_model_url_is_refused_without_quoting_it(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("VLLM_URL", bad)
    monkeypatch.setenv("VLLM_MODEL", "m")
    with pytest.raises(SystemExit, match="VLLM_URL") as refused:
        ModelConfig.from_env()
    assert "secret" not in str(refused.value)


def test_a_model_url_without_credentials_is_used_as_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VLLM_URL", "http://gpu:8000/v1/")
    monkeypatch.setenv("VLLM_MODEL", "m")
    assert ModelConfig.from_env() == ModelConfig(url="http://gpu:8000/v1/", model="m")


def test_credentials_leave_the_url_and_the_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VLLM_URL", "http://us%40er:s%2Fecret@gpu:8000/v1")
    monkeypatch.setenv("VLLM_MODEL", "m")
    config = ModelConfig.from_env()
    assert config.url == "http://gpu:8000/v1"
    assert config.auth == ("us@er", "s/ecret"), "a percent-encoded password must still authenticate"
    assert "ecret" not in repr(config)


def test_the_prompt_shows_the_examples_and_test_inputs_but_never_a_test_output() -> None:
    prompt = ask_for_program(task_prompt(TASK))
    assert "1 2\n3 4" in prompt and "4 3\n2 1" in prompt
    assert "5 6" in prompt and "7 7" in prompt
    assert "6 5" not in prompt and "9 9" not in prompt, "the answer must not reach the model"
    assert "def transform(grid: list[list[int]]) -> list[list[int]]" in prompt
    assert "numpy" in prompt


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"```python\n{PROGRAM}```", PROGRAM),
        (f"```Python\n{PROGRAM}```", PROGRAM),
        (f"```py\n{PROGRAM}```", PROGRAM),
        (f"```\n{PROGRAM}```", PROGRAM),
        (f"```python\nimport numpy\n```\nthen\n```python\n{PROGRAM}```", PROGRAM),
        (f"```python\n{PROGRAM}```\n```python\ndef transform(g):\n    return 2\n```", PROGRAM),
    ],
    ids=["tagged", "capitalized", "py", "bare", "second-block-has-it", "first-of-two"],
)
def test_the_first_python_block_with_a_transform_is_the_program(text: str, expected: str) -> None:
    assert extract_program(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "no code at all",
        PROGRAM,
        f"```python\n{PROGRAM}",
        "```python\nprint('hi')\n```",
        "```python\ndef transform_grid(g):\n    return g\n```",
        f"```javascript\n{PROGRAM}```",
        "",
    ],
    ids=["prose", "unfenced", "unterminated", "no-transform", "other-name", "other-language", "empty"],
)
def test_anything_else_is_unparseable(text: str) -> None:
    assert extract_program(text) is None


async def test_samples_are_requested_with_the_spec_settings(fake: FakeModel, http: httpx.AsyncClient) -> None:
    result = await sample(http, config(fake), DictCache(), "t1", "the prompt", 3)
    assert result.texts == ("completion 0", "completion 1", "completion 2")
    assert (result.fresh, result.cached) == (3, 0)
    assert result.request_ms is not None
    request = fake.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert (request["model"], request["temperature"], request["n"]) == ("m1", 0.8, 3)


async def test_a_second_run_makes_no_request(fake: FakeModel, http: httpx.AsyncClient) -> None:
    cache = DictCache()
    first = await sample(http, config(fake), cache, "t1", "p", 40)
    requests = len(fake.requests)
    second = await sample(http, config(fake), cache, "t1", "p", 40)
    assert len(fake.requests) == requests, "a cached sample must not be paid for twice"
    assert second.texts == first.texts
    assert (second.fresh, second.cached, second.request_ms) == (0, 40, None), "no request means no generation time"


async def test_asking_for_more_samples_requests_only_the_new_ones(fake: FakeModel, http: httpx.AsyncClient) -> None:
    cache = DictCache()
    small = await sample(http, config(fake), cache, "t1", "p", 16)
    fake.requests.clear()
    large = await sample(http, config(fake), cache, "t1", "p", 20)
    assert [request["n"] for request in fake.requests] == [4]
    assert large.texts[:16] == small.texts, "a larger run must extend the smaller one's samples"
    assert (large.fresh, large.cached) == (4, 16)


async def test_asking_for_fewer_samples_uses_the_prefix(fake: FakeModel, http: httpx.AsyncClient) -> None:
    cache = DictCache()
    large = await sample(http, config(fake), cache, "t1", "p", 32)
    fake.requests.clear()
    small = await sample(http, config(fake), cache, "t1", "p", 16)
    assert small.texts == large.texts[:16] and not fake.requests


@pytest.mark.parametrize(
    ("task_id", "prompt", "model_name"),
    [("t2", "p", "m1"), ("t1", "other", "m1"), ("t1", "p", "m2")],
    ids=["other-task", "other-prompt", "other-model"],
)
async def test_each_part_of_the_cache_key_separates_samples(
    fake: FakeModel, http: httpx.AsyncClient, task_id: str, prompt: str, model_name: str
) -> None:
    cache = DictCache()
    await sample(http, config(fake), cache, "t1", "p", 2)
    fake.requests.clear()
    result = await sample(http, config(fake, model_name), cache, task_id, prompt, 2)
    assert result.fresh == 2 and fake.requests, "another model's or task's samples must not be reused"


def test_the_prompt_hash_covers_sampling_settings() -> None:
    base = ModelConfig(url="u", model="m")
    assert prompt_hash(base, "p") == prompt_hash(ModelConfig(url="other", model="m"), "p"), "moving the host keeps samples"
    assert prompt_hash(base, "p") != prompt_hash(ModelConfig(url="u", model="m", temperature=0.2), "p")
    assert prompt_hash(base, "p") != prompt_hash(ModelConfig(url="u", model="m", max_tokens=1), "p")


async def test_large_counts_are_split_into_requests_and_cached_as_they_arrive(
    fake: FakeModel, http: httpx.AsyncClient
) -> None:
    cache = DictCache()
    await sample(http, config(fake), cache, "t1", "p", 40)
    assert [request["n"] for request in fake.requests] == [16, 16, 8]
    assert len(cache.rows) == 40


async def test_requests_overlap_up_to_a_gate_that_tasks_share(fake: FakeModel, http: httpx.AsyncClient) -> None:
    fake.delay_s = 0.2
    gate = asyncio.Semaphore(3)
    first, _ = await asyncio.gather(
        sample(http, config(fake), DictCache(), "t1", "p", 64, gate=gate),
        sample(http, config(fake), DictCache(), "t2", "p", 64, gate=gate),
    )
    assert len(fake.requests) == 8
    assert fake.peak_open_requests == 3, "both tasks wait on the one gate"
    assert first.request_ms is not None
    assert first.request_ms < 4 * 200, "time with a request open isn't the sum over overlapping requests"


async def test_a_refused_request_keeps_what_the_others_returned(fake: FakeModel, http: httpx.AsyncClient) -> None:
    fake.faults.append((400, '{"error": "refused"}'))
    cache = DictCache()
    with pytest.raises(ModelError, match="HTTP 400"):
        await sample(http, config(fake), cache, "t1", "p", 64)
    assert len(cache.rows) == 48


@pytest.mark.parametrize("fault", [500, 503, 429, "drop", "garbage"])
async def test_transient_failures_are_retried(fake: FakeModel, http: httpx.AsyncClient, fault: int | str) -> None:
    fake.faults.extend([fault, fault])
    result = await sample(http, config(fake), DictCache(), "t1", "p", 2)
    assert result.fresh == 2
    assert len(fake.requests) == 3


async def test_a_refused_request_is_not_retried(fake: FakeModel, http: httpx.AsyncClient) -> None:
    fake.faults.append(400)
    with pytest.raises(ModelError, match="HTTP 400"):
        await sample(http, config(fake), DictCache(), "t1", "p", 2)
    assert len(fake.requests) == 1


async def test_giving_up_keeps_what_arrived_and_the_next_run_continues(fake: FakeModel, http: httpx.AsyncClient) -> None:
    cache = DictCache()
    await sample(http, config(fake), cache, "t1", "p", 16)
    fake.faults.extend([500] * 4)
    with pytest.raises(ModelError, match="gave up after 4 attempts"):
        await sample(http, config(fake), cache, "t1", "p", 32)
    assert len(fake.requests) == 5, "one good request, then the first try and three retries"
    assert len(cache.rows) == 16

    fake.requests.clear()
    result = await sample(http, config(fake), cache, "t1", "p", 32)
    assert [request["n"] for request in fake.requests] == [16]
    assert (result.fresh, result.cached) == (16, 16)


async def test_a_short_response_is_topped_up(fake: FakeModel, http: httpx.AsyncClient) -> None:
    fake.max_choices_per_response = 2
    result = await sample(http, config(fake), DictCache(), "t1", "p", 5)
    assert len(result.texts) == 5
    assert [request["n"] for request in fake.requests] == [5, 3, 1]


async def test_text_postgres_would_reject_is_made_storable(http: httpx.AsyncClient) -> None:
    server = FakeModel(lambda prompt: [fenced("x = '\x00'\n"), "\ud800 lone surrogate"])
    with server.running():
        result = await sample(http, ModelConfig(url=server.url, model="m"), DictCache(), "t1", "p", 2)
    for text in result.texts:
        text.encode("utf-8")
        assert "\x00" not in text
