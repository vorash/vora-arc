from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from vora_arc.model import Grid, Pair, Task, TestCase

MAX_SIDE = 30


class TaskFormatError(ValueError):
    pass


def grid_problem(cells: object) -> str | None:
    """Return why `cells` is not a valid ARC grid, or None if it is one."""
    if not isinstance(cells, Sequence) or isinstance(cells, str):
        return f"expected a list of rows, got {type(cells).__name__}"
    if not 1 <= len(cells) <= MAX_SIDE:
        return f"has {len(cells)} rows, expected 1 to {MAX_SIDE}"
    width: int | None = None
    for r, row in enumerate(cells):
        if not isinstance(row, Sequence) or isinstance(row, str):
            return f"row {r} is {type(row).__name__}, expected a list"
        if width is None:
            width = len(row)
            if not 1 <= width <= MAX_SIDE:
                return f"row 0 has {width} cells, expected 1 to {MAX_SIDE}"
        elif len(row) != width:
            return f"row {r} has {len(row)} cells, expected {width} like row 0"
        for c, cell in enumerate(row):
            # bool is an int subclass, so isinstance would let True through.
            if type(cell) is not int or not 0 <= cell <= 9:
                return f"cell [{r}][{c}] is {cell!r}, expected an int 0 to 9"
    return None


def parse_task(task_id: str, raw: object) -> Task:
    """Turn one task's decoded JSON into a Task, rejecting anything malformed."""

    def fail(where: str, what: str) -> TaskFormatError:
        return TaskFormatError(f"task {task_id}: {where}: {what}")

    def grid(where: str, cells: object) -> Grid:
        problem = grid_problem(cells)
        if problem is not None:
            raise fail(where, problem)
        assert isinstance(cells, Sequence)
        return tuple(tuple(row) for row in cells)

    def cases(split: str) -> list[dict[str, object]]:
        items = raw.get(split) if isinstance(raw, dict) else None
        if not isinstance(items, list) or not items:
            raise fail(split, "expected a non-empty list")
        for i, item in enumerate(items):
            if not isinstance(item, dict) or "input" not in item:
                raise fail(f"{split}[{i}]", "expected an object with an input grid")
        return items

    if not isinstance(raw, dict):
        raise fail("top level", f"expected an object, got {type(raw).__name__}")

    train = []
    for i, item in enumerate(cases("train")):
        if "output" not in item:
            raise fail(f"train[{i}]", "missing output grid")
        train.append(
            Pair(grid(f"train[{i}].input", item["input"]), grid(f"train[{i}].output", item["output"]))
        )
    test = [
        TestCase(
            grid(f"test[{i}].input", item["input"]),
            grid(f"test[{i}].output", item["output"]) if "output" in item else None,
        )
        for i, item in enumerate(cases("test"))
    ]
    return Task(id=task_id, train=tuple(train), test=tuple(test))


def load_task(path: Path) -> Task:
    """Load one ARC task file. The task id is the file name without `.json`."""
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise TaskFormatError(f"task {path.stem}: not valid JSON: {e}") from e
    return parse_task(path.stem, raw)


def load_split(directory: Path) -> tuple[Task, ...]:
    """Load every task in a split directory such as `data/arc1/training`, sorted by id."""
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise TaskFormatError(f"no task files in {directory}")
    return tuple(load_task(p) for p in paths)
