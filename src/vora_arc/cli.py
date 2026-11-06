from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import secrets
import sys
from collections.abc import Sequence
from functools import partial
from pathlib import Path

import httpx

from .bench import BenchSettings, run_bench
from .bench_summary import latest_session_by_backend, load_raw, render_summary, summary_exit_code
from .client import PoolMode, connect, open_pool
from .corpus import build_corpus, load_solutions, warmup_candidates
from .generate import REQUEST_TIMEOUT_S, ModelConfig, ModelError, sample
from .leak_report import BACKENDS, LeakReport, read_leak_suites
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
DEFAULT_SOLUTIONS_DIR = Path("solutions")
DEFAULT_CORPUS_SEED = 1


def _non_negative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"expected zero or more, got {text}")
    return value


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
        (
            open_pool(vora, profile, f"vora-arc-solve-{secrets.token_hex(4)}", PoolMode.WARM, max_concurrency)
            if args.pool
            else contextlib.nullcontext(None)
        ) as pool,
    ):
        run_id = await store.begin_run(settings)
        solved = infra_errors = 0
        try:
            print(f"run {run_id}: {len(tasks)} tasks, {args.samples} samples each, model {model.model}", flush=True)
            for task in tasks:
                key = task_key(args.dataset, task)
                await store.register_task(key, args.dataset, args.split)
                result = await solve_task(
                    task,
                    sampler=partial(sample, http, model, store, key),
                    scheduler=partial(schedule, vora, profile, max_concurrency=max_concurrency, pool=pool),
                    samples=args.samples,
                    refine=args.refine,
                )
                await store.save_task_result(run_id, key, result)
                solved += result.solved
                infra_errors += result.infra_errors
                print(f"{task.id}: {'solved' if result.solved else 'unsolved'}, {len(result.candidates)} candidates", flush=True)
            await store.finish_run(run_id)
        except Exception as error:
            await store.finish_run(run_id, f"{type(error).__name__}: {error}")
            if not isinstance(error, ModelError):
                raise
            print(f"run {run_id} failed: {error}", file=sys.stderr)
            return 1
        except BaseException:
            # asyncio.run turns Ctrl-C into a CancelledError here, and raises KeyboardInterrupt after.
            await store.interrupt_run(run_id)
            print(f"run {run_id} interrupted", file=sys.stderr)
            raise
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


async def bench(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    solutions = load_solutions(args.solutions)
    tasks = {solution.task_id: load_task(find_task(args.data_dir, args.dataset, solution.task_id)) for solution in solutions}
    corpus = build_corpus(solutions, args.candidates, args.seed)
    warmup = warmup_candidates(solutions, args.concurrency * 3 if args.warmup is None else args.warmup)
    settings = BenchSettings(PoolMode(args.mode), args.concurrency, args.image_resolved_via, args.server_version)
    async with connect(profile) as vora:
        return await run_bench(profile, corpus, warmup, tasks, settings, args.raw, vora=vora)


async def bench_summary(args: argparse.Namespace) -> int:
    raw = load_raw(*args.raw)
    suites = read_leak_suites(args.leak_pytest, args.leak_vora, latest_session_by_backend(raw))
    print(render_summary(raw, suites), end="")
    return summary_exit_code(raw, suites)


def _leak_report(text: str) -> LeakReport:
    backend, _, path = text.partition("=")
    if backend not in BACKENDS or not path:
        raise argparse.ArgumentTypeError(f"expected BACKEND=PATH with a backend in {BACKENDS}, not {text!r}")
    return LeakReport(backend, Path(path))


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
    solver.add_argument("--pool", action="store_true", help="run programs on a warm pool instead of a fresh sandbox each")
    bencher = commands.add_parser("bench", help="run one arm of experiment 1 and append it to a raw file")
    bencher.add_argument("--mode", required=True, choices=[mode.value for mode in PoolMode])
    bencher.add_argument("--candidates", type=_positive_int, default=10_000, help="candidates in the corpus, each run once")
    bencher.add_argument("--seed", type=int, default=DEFAULT_CORPUS_SEED, help="the corpus seed; arms to compare share it")
    bencher.add_argument("--warmup", type=_non_negative_int, help="runs before measuring (default: 3 x --concurrency)")
    bencher.add_argument("--concurrency", type=_positive_int, default=8)
    bencher.add_argument("--solutions", default=DEFAULT_SOLUTIONS_DIR, type=Path, help="hand-written solutions, one <task id>.py each")
    bencher.add_argument("--dataset", default="arc1", choices=["arc1", "arc2"])
    bencher.add_argument("--data-dir", default=DEFAULT_DATA_DIR, type=Path)
    bencher.add_argument("--profile", type=Path, help="profile TOML (default: $VORA_ARC_PROFILE, then profiles/python-arc.toml)")
    bencher.add_argument("--raw", default=DEFAULT_RESULTS_DIR / "bench" / "experiment-1.jsonl", type=Path)
    bencher.add_argument(
        "--image-resolved-via",
        choices=["containerd", "cache"],
        help="what you checked on the host; a client can't read it (docs/experiment-1.md)",
    )
    bencher.add_argument("--server-version", help="record this instead of asking GET /v1/runners")
    summarizer = commands.add_parser("bench-summary", help="rebuild the summary from raw files")
    summarizer.add_argument("raw", type=Path, nargs="+")
    summarizer.add_argument(
        "--leak-pytest",
        type=_leak_report,
        action="append",
        default=[],
        metavar="BACKEND=PATH",
        help="tests/test_hostile.py's --junitxml file; repeat per backend",
    )
    summarizer.add_argument(
        "--leak-vora",
        type=_leak_report,
        action="append",
        default=[],
        metavar="BACKEND=PATH",
        help="the go test -v output of Vora's leak suites; repeat per backend",
    )
    reporter = commands.add_parser("report", help="write a logged run's Markdown report and charts")
    reporter.add_argument("--run", required=True, help="run id printed by solve")
    reporter.add_argument("--out", default=DEFAULT_RESULTS_DIR, type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    commands_by_name = {
        "run-solution": run_solution,
        "solve": solve,
        "report": write_run_report,
        "bench": bench,
        "bench-summary": bench_summary,
    }
    return asyncio.run(commands_by_name[args.command](args))


if __name__ == "__main__":
    sys.exit(main())
