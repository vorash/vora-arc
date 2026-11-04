from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from vora import Vora

from .client import connect, run_batch
from .model import BatchResult, Task, Verdict
from .profile import DEFAULT_PROFILE_PATH, Profile, load_profile
from .tasks import load_task
from .verify import Failed, Outcome, check_determinism, verify

DEFAULT_DATA_DIR = Path("data")


def find_task(data_dir: Path, dataset: str, task_id: str) -> Path:
    matches = sorted((data_dir / dataset).glob(f"*/{task_id}.json"))
    if not matches:
        raise SystemExit(f"task {task_id} not found under {data_dir / dataset}; run scripts/download_data.sh")
    if len(matches) > 1:
        raise SystemExit(f"task {task_id} is in several splits: {', '.join(map(str, matches))}")
    return matches[0]


async def judge(vora: Vora, profile: Profile, task: Task, program: str, correlation_id: str) -> tuple[Outcome, list[BatchResult]]:
    first = await run_batch(vora, profile, program, task, correlation_id=correlation_id)
    outcome = verify(task, program, first)
    if outcome.verdict is not Verdict.PASSED:
        return outcome, [first]
    second = await run_batch(vora, profile, program, task, correlation_id=f"{correlation_id}/rerun")
    return check_determinism(first, second), [first, second]


def report(outcome: Outcome, runs: list[BatchResult]) -> str:
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
        outcome, runs = await judge(vora, profile, task, program, f"{task.id}/{args.program.stem}")
    print(report(outcome, runs))
    return 0 if outcome.verdict is Verdict.PASSED else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vora-arc")
    commands = parser.add_subparsers(dest="command", required=True)
    solution = commands.add_parser("run-solution", help="run one program in a sandbox and print its verdict")
    solution.add_argument("--task", required=True, help="ARC task id, e.g. 007bbfb7")
    solution.add_argument("--program", required=True, type=Path, help="file defining transform(grid)")
    solution.add_argument("--dataset", default="arc1", choices=["arc1", "arc2"])
    solution.add_argument("--data-dir", default=DEFAULT_DATA_DIR, type=Path)
    solution.add_argument("--profile", default=DEFAULT_PROFILE_PATH, type=Path)
    args = parser.parse_args(argv)
    return asyncio.run(run_solution(args))


if __name__ == "__main__":
    sys.exit(main())
