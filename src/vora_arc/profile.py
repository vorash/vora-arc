from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vora import parse_cpu, parse_size

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parents[2] / "profiles" / "python-arc.toml"


@dataclass(frozen=True)
class Profile:
    name: str
    image: str
    runner_command: tuple[str, ...]
    backend: str
    network: str
    cpu_millis: int
    memory_bytes: int
    pids: int
    ttl_seconds: int
    per_input_timeout_ms: int
    batch_timeout_seconds: int
    output_tail_bytes: int


def load_profile(path: Path = DEFAULT_PROFILE_PATH) -> Profile:
    with path.open("rb") as file:
        raw = tomllib.load(file)
    sandbox = _table(raw, "sandbox")
    runner = _table(raw, "runner")
    command = _field(sandbox, "runner_command", list)
    if not command or not all(isinstance(part, str) for part in command):
        raise ValueError(f"{path}: sandbox.runner_command must be a non-empty list of strings")
    return Profile(
        name=_field(raw, "name", str),
        image=_field(sandbox, "image", str),
        runner_command=tuple(command),
        backend=_field(sandbox, "backend", str),
        network=_field(sandbox, "network", str),
        cpu_millis=parse_cpu(_field(sandbox, "cpu", (int, float, str))),
        memory_bytes=parse_size(_field(sandbox, "memory", (int, str))),
        pids=_field(sandbox, "pids", int),
        ttl_seconds=_field(sandbox, "ttl_seconds", int),
        per_input_timeout_ms=_field(runner, "per_input_timeout_ms", int),
        batch_timeout_seconds=_field(runner, "batch_timeout_seconds", int),
        output_tail_bytes=_field(runner, "output_tail_bytes", int),
    )


def _table(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value: dict[str, Any] = _field(raw, key, dict)
    return value


def _field(table: dict[str, Any], key: str, kind: type | tuple[type, ...]) -> Any:
    if key not in table:
        raise ValueError(f"profile is missing {key!r}")
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, kind):
        raise ValueError(f"profile field {key!r} has the wrong type: {value!r}")
    return value
