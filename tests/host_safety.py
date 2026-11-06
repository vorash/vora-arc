"""What a program may contain before this repository's own tests run it on the host.

`tests/test_corpus.py` and `tests/test_solutions.py` run corpus programs and `solutions/` outside
any sandbox when `data/` is present. Hostile programs must never run there, so this is an allowlist:
anything it doesn't name is refused, including what nobody thought of yet. It only parses a program.
"""

from __future__ import annotations

import ast
import builtins
from collections.abc import Iterable, Iterator
from pathlib import Path

from vora_arc.corpus import build_corpus, load_solutions

IMPORTS = {"time"}
ATTRIBUTES = {"time.monotonic", ".get"}
"""`time.monotonic` for the slow class, and `.get` on a dict for the solutions' colour swaps."""
CALLS = {"ValueError", "bytearray", "helper", "len", "list", "max", "range", "rule", "sorted", "str", "zip"}
"""`rule` is a solution renamed by a template. `helper` doesn't exist, which is how one crash candidate crashes."""
NODES = {
    "Add", "Assign", "Attribute", "BinOp", "Call", "Compare", "Constant", "Dict", "Div", "Eq", "Expr", "FloorDiv",
    "For", "FunctionDef", "Gt", "GtE", "IfExp", "Import", "List", "ListComp", "Load", "Lt", "LtE", "Mod", "Module",
    "Mult", "Name", "NotEq", "Pass", "Raise", "Return", "Slice", "Starred", "Store", "Sub", "Subscript", "Tuple",
    "USub", "UnaryOp", "While", "alias", "arg", "arguments", "comprehension",
}  # fmt: skip

SCANNED_CORPORA = [(seed, 2000) for seed in range(1, 6)] + [(1, 10_000)]


def violations(program: str) -> list[str]:
    """Why this program mustn't run on the host. A program that doesn't parse runs nothing, so it has none."""
    try:
        tree = ast.parse(program)
    except SyntaxError:
        return []
    return [problem for node in ast.walk(tree) if (problem := _problem(node))]


def _problem(node: ast.AST) -> str | None:
    kind = type(node).__name__
    if kind not in NODES:
        return f"{kind} is not an allowed kind of node"
    if isinstance(node, ast.Import):
        names = [(alias.name, alias.asname) for alias in node.names]
        return None if all(name in IMPORTS and asname is None for name, asname in names) else f"import {names}"
    if isinstance(node, ast.Attribute):
        return None if _attribute(node) in ATTRIBUTES else f"attribute .{node.attr}"
    if isinstance(node, ast.Call):
        return _call(node.func)
    if isinstance(node, ast.Name):
        return _name(node.id)
    if isinstance(node, ast.FunctionDef | ast.arg | ast.alias):
        name = node.name if isinstance(node, ast.FunctionDef | ast.alias) else node.arg
        return f"dunder {name}" if name.startswith("__") else None
    return None


def _attribute(node: ast.Attribute) -> str:
    if node.attr == "get":
        return ".get"
    return f"{node.value.id}.{node.attr}" if isinstance(node.value, ast.Name) else f"?.{node.attr}"


def _call(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return None
    if isinstance(func, ast.Name) and func.id in CALLS:
        return None
    return f"call of {ast.unparse(func)}"


def _name(name: str) -> str | None:
    if name.startswith("__"):
        return f"dunder {name}"
    # A builtin that isn't called can still be aliased and called under another name.
    if hasattr(builtins, name) and name not in CALLS:
        return f"builtin {name}"
    return None


def host_safety_failures(programs: Iterable[str]) -> dict[str, list[str]]:
    """Each program this allowlist refuses, with why."""
    found = ((program, violations(program)) for program in programs)
    return {program: problems for program, problems in found if problems}


def programs_for_the_host() -> Iterator[str]:
    """Every program a host test can reach, solutions included: the doc's seeds at the experiment's sizes."""
    solutions = load_solutions(Path(__file__).resolve().parents[1] / "solutions")
    yield from (solution.source for solution in solutions)
    for seed, size in SCANNED_CORPORA:
        yield from (candidate.program for candidate in build_corpus(solutions, size, seed).candidates)
