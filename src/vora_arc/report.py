"""Turn one logged run into Markdown and charts. Every number is read from the database;
what a run didn't measure says so instead of showing zero."""

from __future__ import annotations

import html
import os
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from matplotlib.axes import Axes
from matplotlib.figure import Figure

from .model import Verdict, redact_userinfo
from .store import CandidateRow, RunData
from .vote import Ballot, ballot, vote

NOT_MEASURED = "not measured"
CANDIDATE_COUNTS = (16, 32, 64, 128)
INFRA_ERROR = "Vora failed (no verdict)"
MAX_ERROR_CHARS = 500

_MARKDOWN_INLINE = re.compile(r"[\\`*_\[\]~|]")

_SURFACE = "#fcfcfb"
_INK = "#0b0b0b"
_MUTED = "#52514e"
_GRID = "#e4e3df"
_SERIES = "#2a78d6"


@dataclass(frozen=True)
class Accuracy:
    label: str
    solved: int
    total: int
    note: str = ""

    @property
    def value(self) -> str:
        if not self.total:
            return f"{NOT_MEASURED}{f' ({self.note})' if self.note else ''}"
        return f"{self.solved} / {self.total} ({self.solved / self.total:.1%})"


@dataclass(frozen=True)
class CountPoint:
    count: int
    solved: int | None
    total: int


@dataclass(frozen=True)
class PhaseTime:
    name: str
    seconds: float | None
    basis: str
    note: str = ""


@dataclass(frozen=True)
class Cost:
    gpu_hours: float | None
    eur_per_task: float | None
    note: str


def gpu_price_from_env() -> float | None:
    raw = os.environ.get("GPU_EUR_PER_HOUR")
    if raw is None:
        return None
    try:
        price = float(raw)
    except ValueError:
        raise SystemExit(f"GPU_EUR_PER_HOUR must be a number, got {raw!r}") from None
    if not price > 0:
        raise SystemExit(f"GPU_EUR_PER_HOUR must be above zero, got {raw!r}")
    return price


def accuracy(data: RunData) -> list[Accuracy]:
    """Overall, then per round. Tasks without public test outputs can't be scored."""
    scored = {key for key, task in data.tasks.items() if all(case.output is not None for case in task.test)}
    right = {(a.task_id, a.round) for a in data.answers if a.correct and a.task_id in scored}
    refined = {p.task_id for p in data.phases if p.round == 2} & scored
    round_two = "" if data.run.settings.refine else "run without --refine"
    return [
        Accuracy("Overall, 2 attempts", len({task for task, _ in right}), len(scored), "no scored tasks"),
        Accuracy("Round 1, of all tasks", sum(r == 1 for _, r in right), len(scored), "no scored tasks"),
        Accuracy(
            "Round 2, of the tasks it refined",
            sum(r == 2 for _, r in right),
            len(refined),
            round_two or "no task reached round 2",
        ),
    ]


def accuracy_by_count(data: RunData) -> list[CountPoint]:
    """Round 1 accuracy had the run stopped after the first k samples of each task.

    The completion cache makes a shorter run see exactly these samples. A count above
    the run's --samples was never sampled, so it has no value.
    """
    scored = {key: task for key, task in data.tasks.items() if all(case.output is not None for case in task.test)}
    by_task: dict[str, list[CandidateRow]] = {}
    for candidate in data.candidates:
        if candidate.round == 1:
            by_task.setdefault(candidate.task_id, []).append(candidate)
    points = []
    for count in CANDIDATE_COUNTS:
        if count > data.run.settings.samples or not scored:
            points.append(CountPoint(count, None, len(scored)))
            continue
        solved = 0
        for key, task in scored.items():
            ballots = [
                item
                for c in by_task.get(key, ())
                if c.sample_index < count and (item := _ballot(c)) is not None
            ]
            solved += any(answer.correct for answer in vote(task, ballots))
        points.append(CountPoint(count, solved, len(scored)))
    return points


def verdict_counts(data: RunData) -> dict[str, int]:
    counts = Counter(c.verdict.value if c.verdict else INFRA_ERROR for c in data.candidates)
    table = {verdict.value: counts[verdict.value] for verdict in Verdict}
    if counts[INFRA_ERROR]:
        table[INFRA_ERROR] = counts[INFRA_ERROR]
    return table


def time_split(data: RunData) -> list[PhaseTime]:
    fresh = sum(p.fresh_completions for p in data.phases)
    cached = sum(p.cached_completions for p in data.phases)
    generation = _sum_ms(p.generation_ms for p in data.phases)
    generation_note = (
        f"all {cached} completions came from the cache, so this run logged no generation"
        if fresh == 0 and cached
        else f"covers {fresh} of {fresh + cached} completions; the rest came from the cache"
        if cached
        else ""
    )
    return [
        PhaseTime("generation", generation, "wall-clock with a model request open", generation_note),
        PhaseTime("scheduling", _sum_ms(p.scheduling_ms for p in data.phases), "sum over jobs of the wait for a slot"),
        PhaseTime("startup", _sum_ms(r.startup_ms for r in data.runs), "sum over sandbox runs, seen from the client"),
        PhaseTime("execution", _sum_ms(r.exec_ms for r in data.runs), "sum over sandbox runs, seen from the client"),
        PhaseTime(
            "verification",
            _sum_ms(p.verification_ms for p in data.phases),
            "sum over jobs of verdict and vote computation",
        ),
        PhaseTime(
            "reset",
            _sum_ms(r.reset_ms for r in data.runs),
            "sum over sandbox runs",
            "every run used a fresh sandbox" if data.runs and not any(r.warm_start for r in data.runs) else "",
        ),
    ]


def cost(data: RunData, gpu_eur_per_hour: float | None) -> Cost:
    """GPU-hours are the time this run had a model request open; an idle GPU isn't counted."""
    fresh = sum(p.fresh_completions for p in data.phases)
    cached = sum(p.cached_completions for p in data.phases)
    generation = _sum_ms(p.generation_ms for p in data.phases)
    if generation is None:
        return Cost(None, None, f"no generation was logged in this run ({cached} completions came from the cache)")
    hours = generation / 3600
    note = f"covers {fresh} of {fresh + cached} completions; the rest were paid for by an earlier run" if cached else ""
    if gpu_eur_per_hour is None:
        return Cost(hours, None, "GPU_EUR_PER_HOUR is not set")
    return Cost(hours, hours * gpu_eur_per_hour / len(data.tasks), note)


def render_markdown(data: RunData, gpu_eur_per_hour: float | None, charts: dict[str, str]) -> str:
    settings = data.run.settings
    lines = [
        f"# Run {data.run.id}",
        "",
        f"- Dataset: {settings.dataset} {settings.split}, {len(data.tasks)} tasks"
        + (f" (limit {settings.task_limit})" if settings.task_limit else ""),
        f"- Model: {settings.model}; {settings.samples} samples per task; refinement {'on' if settings.refine else 'off'}",
        f"- Sandbox: profile {settings.profile}, backend {settings.backend}, at most {settings.max_concurrency} at a time",
        f"- Status: {data.run.status}" + (f": {_inline_text(data.run.error)}" if data.run.error else ""),
        f"- Total wall-clock: {_run_wall_clock(data)}",
    ]
    if data.run.status != "finished":
        lines += ["", f"**This run did not finish. These numbers cover only what it logged: {len(data.tasks)} tasks.**"]

    lines += ["", "## Accuracy", "", "| | Solved |", "|---|---|"]
    lines += [f"| {row.label} | {row.value} |" for row in accuracy(data)]
    lines += _multi_test_note(data)

    lines += ["", "## Accuracy vs candidate count", ""]
    lines += [
        f"Round 1, re-voted on the first k samples of each task in this run. Refinement isn't included. "
        f"A count above this run's {settings.samples} samples is {NOT_MEASURED}.",
        "",
        "| Candidates per task | Solved |",
        "|---|---|",
    ]
    for point in accuracy_by_count(data):
        value = NOT_MEASURED if point.solved is None else f"{point.solved} / {point.total} ({point.solved / point.total:.1%})"
        lines.append(f"| {point.count} | {value} |")
    lines += _chart(charts, "accuracy")

    lines += ["", "## Verdicts", ""]
    if data.candidates:
        distinct = sum(not c.is_duplicate and c.program is not None for c in data.candidates)
        lines += [
            f"{len(data.candidates)} candidates, {distinct} distinct programs, {len(data.runs)} sandbox runs. "
            "A duplicate counts under its first copy's verdict.",
            "",
            "| Verdict | Candidates |",
            "|---|---|",
        ]
        lines += [f"| {verdict} | {count} |" for verdict, count in verdict_counts(data).items()]
        lines += _chart(charts, "verdicts")
    else:
        lines.append(f"{NOT_MEASURED}: this run logged no candidates.")

    lines += ["", "## Time split", "", "| Phase | Time | Basis |", "|---|---|---|"]
    for phase in time_split(data):
        value = NOT_MEASURED if phase.seconds is None else _seconds(phase.seconds)
        note = f" ({phase.note})" if phase.note else ""
        lines.append(f"| {phase.name} | {value}{note} | {phase.basis} |")
    lines += ["", "Sums over jobs overlap when jobs run at once, so they don't add up to the wall-clock."]

    run_cost = cost(data, gpu_eur_per_hour)
    gpu_hours = NOT_MEASURED if run_cost.gpu_hours is None else f"{run_cost.gpu_hours:.6f}"
    per_task = NOT_MEASURED if run_cost.eur_per_task is None else f"{run_cost.eur_per_task:.6f} EUR"
    lines += [
        "",
        "## Cost per task",
        "",
        f"- GPU-hours (time with a model request open): {gpu_hours}",
        f"- Price: {NOT_MEASURED if gpu_eur_per_hour is None else f'{gpu_eur_per_hour} EUR per hour'}",
        f"- Cost per task: {per_task}" + (f" ({run_cost.note})" if run_cost.note else ""),
    ]
    return "\n".join(lines) + "\n"


def write_report(data: RunData, directory: Path, gpu_eur_per_hour: float | None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    charts: dict[str, str] = {}
    if _accuracy_chart(accuracy_by_count(data), directory / "accuracy_vs_candidates.png"):
        charts["accuracy"] = "accuracy_vs_candidates.png"
    if _verdict_chart(verdict_counts(data), directory / "verdicts.png"):
        charts["verdicts"] = "verdicts.png"
    path = directory / "report.md"
    path.write_text(render_markdown(data, gpu_eur_per_hour, charts))
    return path


def _inline_text(text: str) -> str:
    """Untrusted text as part of one Markdown line: it can't open a block, a link or a tag."""
    line = " ".join(redact_userinfo(text).split())
    if len(line) > MAX_ERROR_CHARS:
        line = line[:MAX_ERROR_CHARS] + "..."
    return _MARKDOWN_INLINE.sub(r"\\\g<0>", html.escape(line, quote=False))


def _ballot(candidate: CandidateRow) -> Ballot | None:
    if candidate.verdict is not Verdict.PASSED or candidate.program is None:
        return None
    return ballot(candidate.program, candidate.grids)


def _sum_ms(values: Iterable[float | None]) -> float | None:
    """Seconds, or None when nothing was measured. A measured zero stays a zero."""
    measured = [value for value in values if value is not None]
    return sum(measured) / 1000 if measured else None


def _seconds(value: float) -> str:
    # Verification takes microseconds per job, which "0.000 s" would hide.
    return f"{value:.3f} s" if value >= 1 else f"{value * 1000:.3f} ms"


def _run_wall_clock(data: RunData) -> str:
    if data.run.finished_at is None:
        return NOT_MEASURED
    return _seconds((data.run.finished_at - data.run.started_at).total_seconds())


def _multi_test_note(data: RunData) -> list[str]:
    several = sum(len(task.test) > 1 for task in data.tasks.values())
    if not several:
        return []
    return ["", f"{several} tasks have several test inputs. Each counts as solved only if one answer gets all of them right."]


def _chart(charts: dict[str, str], name: str) -> list[str]:
    return ["", f"![{name}]({charts[name]})"] if name in charts else []


def _style(axes: Axes) -> None:
    axes.set_facecolor(_SURFACE)
    axes.tick_params(colors=_MUTED, length=0)
    for side in ("top", "right", "left"):
        axes.spines[side].set_visible(False)
    axes.spines["bottom"].set_color(_GRID)
    axes.set_axisbelow(True)


def _accuracy_chart(points: list[CountPoint], path: Path) -> bool:
    measured = [p for p in points if p.solved is not None]
    if not measured:
        return False
    figure = Figure(figsize=(7, 4), facecolor=_SURFACE)
    axes = figure.subplots()
    _style(axes)
    xs = [p.count for p in measured]
    ys = [100 * (p.solved or 0) / p.total for p in measured]
    axes.plot(xs, ys, color=_SERIES, linewidth=2, marker="o", markersize=8, markeredgecolor=_SURFACE, markeredgewidth=2)
    axes.set_xscale("log", base=2)
    axes.set_xticks([p.count for p in points], [str(p.count) for p in points])
    axes.minorticks_off()
    axes.set_xlim(CANDIDATE_COUNTS[0] / 1.3, CANDIDATE_COUNTS[-1] * 1.3)
    axes.set_ylim(0, 105)
    axes.set_yticks(range(0, 101, 20))
    axes.grid(axis="y", color=_GRID, linewidth=1)
    axes.set_xlabel("Candidates per task", color=_MUTED)
    axes.set_ylabel("Tasks solved (%)", color=_MUTED)
    axes.set_title("Round 1 accuracy vs candidate count", color=_INK, loc="left")
    missing = [str(p.count) for p in points if p.solved is None]
    if missing:
        axes.annotate(
            f"{NOT_MEASURED}: {', '.join(missing)}", xy=(1, 1), xycoords="axes fraction", ha="right", va="bottom", color=_MUTED
        )
    figure.savefig(path, dpi=150, bbox_inches="tight")
    return True


def _verdict_chart(counts: dict[str, int], path: Path) -> bool:
    if not any(counts.values()):
        return False
    labels = list(counts)[::-1]
    values = [counts[label] for label in labels]
    figure = Figure(figsize=(7, 0.45 * len(labels) + 1), facecolor=_SURFACE)
    axes = figure.subplots()
    _style(axes)
    axes.barh(labels, values, color=_SERIES, height=0.6)
    axes.bar_label(axes.containers[0], padding=4, color=_INK)  # type: ignore[arg-type]
    axes.set_xlim(0, max(values) * 1.12)
    axes.xaxis.set_visible(False)
    axes.spines["bottom"].set_visible(False)
    axes.tick_params(axis="y", labelcolor=_INK)
    axes.set_title("Candidates by verdict", color=_INK, loc="left")
    figure.savefig(path, dpi=150, bbox_inches="tight")
    return True
