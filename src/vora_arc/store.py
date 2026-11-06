"""PostgreSQL persistence: the completion cache and everything a solve run logged."""

from __future__ import annotations

import contextlib
import os
import secrets
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .model import Grid, GridResult, GridStatus, Task, Verdict, redact_userinfo, storable_text
from .pipeline import CandidateResult, TaskResult
from .tasks import parse_task

DATABASE_URL_ENV = "VORA_ARC_DATABASE_URL"

# Spec tables, plus what telling runs apart and reporting honestly need:
#   solve_runs           one row per `vora-arc solve`; the spec's `runs` means sandbox runs.
#   solve_run_tasks      each task as that run solved it, which is what its report scores
#                        against. `tasks` holds only ids: a task file can be corrected between runs.
#   candidates.run_id, answers.run_id, answers.round
#   candidates.sample_index, prompt_hash  tie a candidate to its completion, and let
#                        a report re-vote on the first k samples.
#   candidates.infra_error  Vora failed: no verdict, and no pretending there was one.
#   runs.attempt, runs.exec_ms  the determinism re-run, and the execution phase.
#   task_phases          the time a run spent outside its sandboxes.
SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id text PRIMARY KEY,
    dataset text NOT NULL,
    split text NOT NULL
);
CREATE TABLE IF NOT EXISTS completions (
    task_id text NOT NULL REFERENCES tasks (id),
    prompt_hash text NOT NULL,
    sample_index integer NOT NULL,
    model text NOT NULL,
    text text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, prompt_hash, sample_index)
);
CREATE TABLE IF NOT EXISTS solve_runs (
    id text PRIMARY KEY,
    dataset text NOT NULL,
    split text NOT NULL,
    task_limit integer,
    samples integer NOT NULL,
    refine boolean NOT NULL,
    model text NOT NULL,
    profile text NOT NULL,
    backend text NOT NULL,
    max_concurrency integer NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'finished', 'failed', 'interrupted')),
    error text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE TABLE IF NOT EXISTS solve_run_tasks (
    run_id text NOT NULL REFERENCES solve_runs (id),
    task_id text NOT NULL REFERENCES tasks (id),
    json jsonb NOT NULL,
    PRIMARY KEY (run_id, task_id)
);
CREATE TABLE IF NOT EXISTS candidates (
    id bigserial PRIMARY KEY,
    run_id text NOT NULL REFERENCES solve_runs (id),
    task_id text NOT NULL REFERENCES tasks (id),
    round integer NOT NULL,
    sample_index integer NOT NULL,
    prompt_hash text NOT NULL,
    program text,
    program_sha256 text,
    duplicate_of bigint REFERENCES candidates (id),
    verdict text,
    cell_accuracy double precision,
    infra_error text,
    UNIQUE (run_id, task_id, round, sample_index),
    FOREIGN KEY (task_id, prompt_hash, sample_index) REFERENCES completions (task_id, prompt_hash, sample_index),
    CHECK ((verdict IS NULL) = (infra_error IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS runs (
    id bigserial PRIMARY KEY,
    candidate_id bigint NOT NULL REFERENCES candidates (id),
    attempt integer NOT NULL,
    run_status text NOT NULL,
    result_json jsonb NOT NULL,
    cpu_ms bigint,
    peak_mem_bytes bigint,
    warm_start boolean NOT NULL,
    startup_ms integer NOT NULL,
    exec_ms integer NOT NULL,
    reset_ms integer,
    audit_log_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (candidate_id, attempt)
);
CREATE TABLE IF NOT EXISTS answers (
    run_id text NOT NULL REFERENCES solve_runs (id),
    task_id text NOT NULL REFERENCES tasks (id),
    round integer NOT NULL,
    rank integer NOT NULL,
    output_json jsonb NOT NULL,
    votes integer NOT NULL,
    correct boolean,
    PRIMARY KEY (run_id, task_id, rank)
);
CREATE TABLE IF NOT EXISTS task_phases (
    run_id text NOT NULL REFERENCES solve_runs (id),
    task_id text NOT NULL REFERENCES tasks (id),
    round integer NOT NULL,
    generation_ms integer,
    fresh_completions integer NOT NULL,
    cached_completions integer NOT NULL,
    scheduling_ms integer,
    verification_ms double precision,
    PRIMARY KEY (run_id, task_id, round)
);
"""


@dataclass(frozen=True)
class RunSettings:
    dataset: str
    split: str
    task_limit: int | None
    samples: int
    refine: bool
    model: str
    profile: str
    backend: str
    max_concurrency: int


@dataclass(frozen=True)
class SolveRun:
    id: str
    settings: RunSettings
    status: str
    error: str | None
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class CandidateRow:
    task_id: str
    round: int
    sample_index: int
    program: str | None
    is_duplicate: bool
    verdict: Verdict | None
    infra_error: str | None
    grids: tuple[GridResult, ...]
    """A passed candidate's test results from its first run, shared with its first copy.
    A report votes on nothing else, so nothing else is loaded."""


@dataclass(frozen=True)
class RunRow:
    startup_ms: int
    exec_ms: int
    warm_start: bool
    reset_ms: int | None


@dataclass(frozen=True)
class PhaseRow:
    task_id: str
    round: int
    generation_ms: int | None
    fresh_completions: int
    cached_completions: int
    scheduling_ms: int | None
    verification_ms: float | None


@dataclass(frozen=True)
class AnswerRow:
    task_id: str
    round: int
    rank: int
    votes: int
    correct: bool | None


@dataclass(frozen=True)
class RunData:
    run: SolveRun
    tasks: Mapping[str, Task]
    candidates: tuple[CandidateRow, ...]
    runs: tuple[RunRow, ...]
    phases: tuple[PhaseRow, ...]
    answers: tuple[AnswerRow, ...]


def task_key(dataset: str, task: Task) -> str:
    """The stored task id. ARC-AGI-1 and ARC-AGI-2 share 773 ids, each with different grids."""
    return f"{dataset}/{task.id}"


def database_url_from_env() -> str:
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise SystemExit(f"set {DATABASE_URL_ENV} to the PostgreSQL database for this solver's results")
    return url


@contextlib.asynccontextmanager
async def open_store(url: str) -> AsyncIterator[Store]:
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as connection:
        store = Store(connection)
        await store.ensure_schema()
        yield store


class Store:
    def __init__(self, connection: psycopg.AsyncConnection[Any]) -> None:
        self._connection = connection

    async def ensure_schema(self) -> None:
        await self._connection.execute(SCHEMA)

    async def load_completions(self, task_id: str, prompt_hash: str) -> dict[int, str]:
        cursor = await self._connection.execute(
            "SELECT sample_index, text FROM completions WHERE task_id = %s AND prompt_hash = %s",
            (task_id, prompt_hash),
        )
        return {index: text for index, text in await cursor.fetchall()}

    async def save_completions(self, task_id: str, prompt_hash: str, model: str, texts: Mapping[int, str]) -> dict[int, str]:
        async with self._connection.cursor() as cursor:
            await cursor.executemany(
                "INSERT INTO completions (task_id, prompt_hash, sample_index, model, text) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                [(task_id, prompt_hash, index, model, text) for index, text in texts.items()],
            )
            await cursor.execute(
                "SELECT sample_index, text FROM completions WHERE task_id = %s AND prompt_hash = %s AND sample_index = ANY(%s)",
                (task_id, prompt_hash, list(texts)),
            )
            return {index: text for index, text in await cursor.fetchall()}

    async def register_task(self, key: str, dataset: str, split: str) -> None:
        await self._connection.execute(
            "INSERT INTO tasks (id, dataset, split) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (key, dataset, split),
        )

    async def begin_run(self, settings: RunSettings) -> str:
        run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
        await self._connection.execute(
            "INSERT INTO solve_runs (id, dataset, split, task_limit, samples, refine, model, profile, backend, "
            "max_concurrency, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'running')",
            (
                run_id,
                settings.dataset,
                settings.split,
                settings.task_limit,
                settings.samples,
                settings.refine,
                settings.model,
                settings.profile,
                settings.backend,
                settings.max_concurrency,
            ),
        )
        return run_id

    async def finish_run(self, run_id: str, error: str | None = None) -> None:
        await self._connection.execute(
            "UPDATE solve_runs SET status = %s, error = %s, finished_at = now() WHERE id = %s",
            ("failed" if error else "finished", storable_text(redact_userinfo(error)) if error else None, run_id),
        )

    async def interrupt_run(self, run_id: str) -> None:
        await self._connection.execute(
            "UPDATE solve_runs SET status = 'interrupted', finished_at = now() WHERE id = %s", (run_id,)
        )

    async def save_task_result(self, run_id: str, key: str, result: TaskResult) -> None:
        """Write one task as it was solved, with its candidates, runs, answers and timings, or none of it."""
        async with self._connection.transaction():
            await self._connection.execute(
                "INSERT INTO solve_run_tasks (run_id, task_id, json) VALUES (%s, %s, %s)",
                (run_id, key, Jsonb(_task_json(result.task))),
            )
            ids: dict[tuple[int, int], int] = {}
            for candidate in result.candidates:
                ids[(candidate.round, candidate.sample_index)] = await self._insert_candidate(
                    run_id, key, candidate, ids
                )
            for answer in result.answers:
                await self._connection.execute(
                    "INSERT INTO answers (run_id, task_id, round, rank, output_json, votes, correct) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (run_id, key, result.answer_round, answer.rank, Jsonb(answer.outputs), answer.votes, answer.correct),
                )
            for timing in result.timings:
                await self._connection.execute(
                    "INSERT INTO task_phases (run_id, task_id, round, generation_ms, fresh_completions, "
                    "cached_completions, scheduling_ms, verification_ms) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        run_id,
                        key,
                        timing.round,
                        timing.generation_ms,
                        timing.fresh_completions,
                        timing.cached_completions,
                        timing.scheduling_ms,
                        timing.verification_ms,
                    ),
                )

    async def _insert_candidate(
        self, run_id: str, key: str, candidate: CandidateResult, ids: Mapping[tuple[int, int], int]
    ) -> int:
        cursor = await self._connection.execute(
            "INSERT INTO candidates (run_id, task_id, round, sample_index, prompt_hash, program, program_sha256, "
            "duplicate_of, verdict, cell_accuracy, infra_error) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                run_id,
                key,
                candidate.round,
                candidate.sample_index,
                candidate.prompt_hash,
                candidate.program,
                candidate.program_sha256,
                ids[candidate.first_copy] if candidate.first_copy else None,
                candidate.verdict,
                candidate.cell_accuracy,
                storable_text(candidate.infra_error) if candidate.infra_error else None,
            ),
        )
        row = await cursor.fetchone()
        assert row is not None
        candidate_id: int = row[0]
        for attempt, run in enumerate(candidate.runs, start=1):
            await self._connection.execute(
                "INSERT INTO runs (candidate_id, attempt, run_status, result_json, cpu_ms, peak_mem_bytes, warm_start, "
                "startup_ms, exec_ms, reset_ms, audit_log_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    candidate_id,
                    attempt,
                    run.run_status,
                    Jsonb(_clean(asdict(run))),
                    run.cpu_ms,
                    run.peak_mem_bytes,
                    run.warm_start,
                    run.startup_ms,
                    run.exec_ms,
                    run.reset_ms,
                    run.audit_log_id,
                ),
            )
        return candidate_id

    async def load_run(self, run_id: str) -> RunData | None:
        async with self._connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute("SELECT * FROM solve_runs WHERE id = %s", (run_id,))
            row = await cursor.fetchone()
            if row is None:
                return None
            await cursor.execute("SELECT task_id, json FROM solve_run_tasks WHERE run_id = %s", (run_id,))
            tasks = {r["task_id"]: parse_task(r["task_id"].split("/", 1)[1], r["json"]) for r in await cursor.fetchall()}
            await cursor.execute(
                "SELECT c.task_id, c.round, c.sample_index, c.program, c.duplicate_of IS NOT NULL AS is_duplicate, "
                "c.verdict, c.infra_error, "
                "jsonb_path_query_array(r.result_json -> 'grids', '$[*] ? (@.is_test == true)') AS grids "
                "FROM candidates c LEFT JOIN runs r ON c.verdict = 'passed' "
                "AND r.candidate_id = COALESCE(c.duplicate_of, c.id) AND r.attempt = 1 "
                "WHERE c.run_id = %s ORDER BY c.task_id, c.round, c.sample_index",
                (run_id,),
            )
            candidates = tuple(_candidate_row(r) for r in await cursor.fetchall())
            await cursor.execute(
                "SELECT r.startup_ms, r.exec_ms, r.warm_start, r.reset_ms FROM runs r "
                "JOIN candidates c ON c.id = r.candidate_id WHERE c.run_id = %s",
                (run_id,),
            )
            runs = tuple(RunRow(**r) for r in await cursor.fetchall())
            await cursor.execute(
                "SELECT task_id, round, generation_ms, fresh_completions, cached_completions, scheduling_ms, "
                "verification_ms FROM task_phases WHERE run_id = %s ORDER BY task_id, round",
                (run_id,),
            )
            phases = tuple(PhaseRow(**r) for r in await cursor.fetchall())
            await cursor.execute(
                "SELECT task_id, round, rank, votes, correct FROM answers WHERE run_id = %s ORDER BY task_id, rank",
                (run_id,),
            )
            answers = tuple(AnswerRow(**r) for r in await cursor.fetchall())
        settings = RunSettings(
            row["dataset"],
            row["split"],
            row["task_limit"],
            row["samples"],
            row["refine"],
            row["model"],
            row["profile"],
            row["backend"],
            row["max_concurrency"],
        )
        run = SolveRun(row["id"], settings, row["status"], row["error"], row["started_at"], row["finished_at"])
        return RunData(run, tasks, candidates, runs, phases, answers)


def _candidate_row(row: dict[str, Any]) -> CandidateRow:
    return CandidateRow(
        row["task_id"],
        row["round"],
        row["sample_index"],
        row["program"],
        row["is_duplicate"],
        Verdict(row["verdict"]) if row["verdict"] else None,
        row["infra_error"],
        tuple(_grid_result(g) for g in row["grids"] or ()),
    )


def _grid_result(raw: dict[str, Any]) -> GridResult:
    output: Grid | None = None if raw["output"] is None else tuple(tuple(r) for r in raw["output"])
    return GridResult(raw["index"], raw["is_test"], GridStatus(raw["status"]), output, raw["error"], raw["wall_ms"])


def _task_json(task: Task) -> dict[str, Any]:
    return {
        "train": [{"input": pair.input, "output": pair.output} for pair in task.train],
        "test": [
            {"input": case.input} | ({} if case.output is None else {"output": case.output}) for case in task.test
        ],
    }


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return storable_text(value)
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value
