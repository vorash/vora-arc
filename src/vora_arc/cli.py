from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from functools import partial
from pathlib import Path

import httpx

from .client import connect
from .generate import REQUEST_TIMEOUT_S, ModelConfig, ModelError, sample
from .model import BatchResult, Verdict
from .pipeline import solve_task
from .profile import load_profile
from .report import gpu_price_from_env, write_report
from .schedule import judge, max_concurrency_from_env, schedule
from .store import RunSettings, database_url_from_env, open_store, task_key
from .tasks import load_split, load_task
from .verify import Failed, Outcome

DEFAULT_DATA_DIR = Path("data")
DEFAULT_RESULTS_DIR = Path("results")


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {text}")
    return value


def find_task(data_dir: Path, dataset: str, task_id: str) -> Path:
    matches = sorted((data_dir / dataset).glob(f"*/{task_id}.json"))
    if not matches:
        raise SystemExit(f"task {task_id} not found under {data_dir / dataset}; run scripts/download_data.sh")
    if len(matches) > 1:
        raise SystemExit(f"task {task_id} is in several splits: {', '.join(map(str, matches))}")
    return matches[0]


def describe(outcome: Outcome, runs: Sequence[BatchResult]) -> str:
    lines = [f"verdict: {outcome.verdict}"]
    if isinstance(outcome, Failed):
        lines.append(f"cell accuracy: {outcome.cell_accuracy:.3f}")
    for number, run in enumerate(runs, start=1):
        lines.append(
            f"run {number}: {run.run_status} sandbox={run.sandbox_id} "
            f"startup={run.startup_ms}ms exec={run.exec_ms}ms peak_mem={run.peak_mem_bytes}"
        )
        for grid in run.grids:
            kind = "test" if grid.is_test else "train"
            error = f" {grid.error.splitlines()[-1]}" if grid.error else ""
            lines.append(f"  {kind}[{grid.index}] {grid.status} {grid.wall_ms}ms{error}")
    return "\n".join(lines)


async def run_solution(args: argparse.Namespace) -> int:
    task = load_task(find_task(args.data_dir, args.dataset, args.task))
    program = args.program.read_text()
    profile = load_profile(args.profile)
    async with connect(profile) as vora:
        judgement = await judge(vora, profile, task, program, f"{task.id}/{args.program.stem}")
    print(describe(judgement.outcome, judgement.runs))
    return 0 if judgement.outcome.verdict is Verdict.PASSED else 1


async def solve(args: argparse.Namespace) -> int:
    model = ModelConfig.from_env()
    url = database_url_from_env()
    profile = load_profile(args.profile)
    max_concurrency = max_concurrency_from_env()
    tasks = load_split(args.data_dir / args.dataset / args.split)[: args.limit]
    settings = RunSettings(
        args.dataset,
        args.split,
        args.limit,
        args.samples,
        args.refine,
        model.model,
        profile.name,
        profile.backend,
        max_concurrency,
    )
    async with (
        open_store(url) as store,
        connect(profile) as vora,
        httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as http,
    ):
        run_id = await store.begin_run(settings)
        print(f"run {run_id}: {len(tasks)} tasks, {args.samples} samples each, model {model.model}", flush=True)
        solved = infra_errors = 0
        try:
            for task in tasks:
                key = task_key(args.dataset, task)
                await store.register_task(key, args.dataset, args.split)
                result = await solve_task(
                    task,
                    sampler=partial(sample, http, model, store, key),
                    scheduler=partial(schedule, vora, profile, max_concurrency=max_concurrency),
                    samples=args.samples,
                    refine=args.refine,
                )
                await store.save_task_result(run_id, key, result)
                solved += result.solved
                infra_errors += result.infra_errors
                print(f"{task.id}: {'solved' if result.solved else 'unsolved'}, {len(result.candidates)} candidates", flush=True)
        except Exception as error:
            await store.finish_run(run_id, f"{type(error).__name__}: {error}")
            if not isinstance(error, ModelError):
                raise
            print(f"run {run_id} failed: {error}", file=sys.stderr)
            return 1
        await store.finish_run(run_id)
    print(f"run {run_id}: solved {solved} of {len(tasks)}; report with: vora-arc report --run {run_id}")
    if infra_errors:
        print(f"run {run_id}: Vora failed on {infra_errors} candidates, so they have no verdict", file=sys.stderr)
        return 1
    return 0


async def write_run_report(args: argparse.Namespace) -> int:
    async with open_store(database_url_from_env()) as store:
        data = await store.load_run(args.run)
    if data is None:
        raise SystemExit(f"no run {args.run} in the database")
    path = write_report(data, args.out / args.run, gpu_price_from_env())
    print(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vora-arc")
    commands = parser.add_subparsers(dest="command", required=True)
    solution = commands.add_parser("run-solution", help="run one program in a sandbox and print its verdict")
    solution.add_argument("--task", required=True, help="ARC task id, e.g. 007bbfb7")
    solution.add_argument("--program", required=True, type=Path, help="file defining transform(grid)")
    solution.add_argument("--dataset", default="arc1", choices=["arc1", "arc2"])
    solution.add_argument("--data-dir", default=DEFAULT_DATA_DIR, type=Path)
    solution.add_argument("--profile", type=Path, help="profile TOML (default: $VORA_ARC_PROFILE, then profiles/python-arc.toml)")
    solver = commands.add_parser("solve", help="sample programs from a model, judge them in sandboxes, and vote")
    solver.add_argument("--dataset", default="arc1", choices=["arc1", "arc2"])
    solver.add_argument("--split", default="evaluation", choices=["training", "evaluation"])
    solver.add_argument("--limit", type=_positive_int, help="solve only the first N tasks by id (default: all)")
    solver.add_argument("--samples", type=_positive_int, default=64, help="completions per task")
    solver.add_argument("--refine", action="store_true", help="give a task with no passed candidate a second round")
    solver.add_argument("--data-dir", default=DEFAULT_DATA_DIR, type=Path)
    solver.add_argument("--profile", type=Path, help="profile TOML (default: $VORA_ARC_PROFILE, then profiles/python-arc.toml)")
    reporter = commands.add_parser("report", help="write a logged run's Markdown report and charts")
    reporter.add_argument("--run", required=True, help="run id printed by solve")
    reporter.add_argument("--out", default=DEFAULT_RESULTS_DIR, type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    commands_by_name = {"run-solution": run_solution, "solve": solve, "report": write_run_report}
    return asyncio.run(commands_by_name[args.command](args))


if __name__ == "__main__":
    sys.exit(main())
