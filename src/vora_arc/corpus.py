"""The candidates experiment 1 runs: a pure function of a seed, a size and `solutions/`.

Same inputs, same candidates in the same order, so every arm runs exactly the same programs.
docs/experiment-1.md explains the mix.
"""

from __future__ import annotations

import ast
import hashlib
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class CandidateClass(StrEnum):
    HAND_WRITTEN = "hand_written"
    MUTATED = "mutated"
    SYNTAX_ERROR = "syntax_error"
    MISSING_TRANSFORM = "missing_transform"
    WRONG_SHAPE = "wrong_shape"
    CRASH = "crash"
    SLOW = "slow"
    MEMORY_HUNGRY = "memory_hungry"
    TIMEOUT = "timeout"


MIX_DENOMINATOR = 10_000
# Parts of MIX_DENOMINATOR. Slow, memory-hungry and timeout stay under 1% together, so the
# overall p99 is an ordinary program's and these show in their own rows and the max.
MIX: Mapping[CandidateClass, int] = {
    CandidateClass.HAND_WRITTEN: 1000,
    CandidateClass.MUTATED: 5010,
    CandidateClass.SYNTAX_ERROR: 1000,
    CandidateClass.MISSING_TRANSFORM: 500,
    CandidateClass.WRONG_SHAPE: 1200,
    CandidateClass.CRASH: 1200,
    CandidateClass.SLOW: 50,
    CandidateClass.MEMORY_HUNGRY: 30,
    CandidateClass.TIMEOUT: 10,
}

# Far enough from the runner's 2 s per input and the sandbox's 256 MiB that the verdict
# can't depend on the arm. Going over either limit is the hostile suite's job.
SLOW_SECONDS = (0.1, 0.15, 0.2)
MEMORY_MIB = (64, 80, 96)


@dataclass(frozen=True)
class Solution:
    task_id: str
    source: str


@dataclass(frozen=True)
class Candidate:
    index: int
    candidate_class: CandidateClass
    task_id: str
    program: str
    program_sha256: str


@dataclass(frozen=True)
class Corpus:
    seed: int
    mix: Mapping[CandidateClass, int]
    counts: Mapping[CandidateClass, int]
    distinct_programs: Mapping[CandidateClass, int]
    candidates: tuple[Candidate, ...]
    sha256: str


def load_solutions(directory: Path) -> tuple[Solution, ...]:
    solutions = tuple(Solution(path.stem, path.read_text()) for path in sorted(directory.glob("*.py")))
    if not solutions:
        raise SystemExit(f"no solutions in {directory}")
    return solutions


def composition(candidates: int, mix: Mapping[CandidateClass, int] = MIX) -> dict[CandidateClass, int]:
    """Largest-remainder rounding, so the counts always add up. A tie goes to the class listed first."""
    total = sum(mix.values())
    if total != MIX_DENOMINATOR:
        raise ValueError(f"a mix adds up to {MIX_DENOMINATOR}, not {total}")
    counts = {name: candidates * parts // total for name, parts in mix.items()}
    remainders = sorted(mix, key=lambda name: candidates * mix[name] % total, reverse=True)
    for name in remainders[: candidates - sum(counts.values())]:
        counts[name] += 1
    return counts


def build_corpus(
    solutions: Sequence[Solution], candidates: int, seed: int, mix: Mapping[CandidateClass, int] = MIX
) -> Corpus:
    counts = composition(candidates, mix)
    rng = random.Random(seed)
    drafts = [
        (name, solutions[n % len(solutions)].task_id, _MAKERS[name](solutions[n % len(solutions)], rng))
        for name, count in counts.items()
        for n in range(count)
    ]
    rng.shuffle(drafts)
    items = tuple(_candidate(index, *draft) for index, draft in enumerate(drafts))
    distinct = {name: len({item.program_sha256 for item in items if item.candidate_class is name}) for name in counts}
    digest = hashlib.sha256()
    for item in items:
        digest.update(f"{item.index} {item.candidate_class} {item.task_id} {item.program_sha256}\n".encode())
    return Corpus(seed, mix, counts, distinct, items, digest.hexdigest())


def warmup_candidates(solutions: Sequence[Solution], count: int) -> tuple[Candidate, ...]:
    """Hand-written only: warmup fills the pool, and a junk program there would only add noise."""
    return tuple(
        _candidate(
            index,
            CandidateClass.HAND_WRITTEN,
            solutions[index % len(solutions)].task_id,
            solutions[index % len(solutions)].source,
        )
        for index in range(count)
    )


def _candidate(index: int, name: CandidateClass, task_id: str, program: str) -> Candidate:
    return Candidate(index, name, task_id, program, hashlib.sha256(program.encode()).hexdigest())


def _renamed(solution: Solution, name: str = "rule") -> str:
    return solution.source.replace("def transform(", f"def {name}(", 1)


def _wrapped(solution: Solution, body: str, *, imports: str = "") -> str:
    return f"{_renamed(solution)}\n\n{imports}def transform(grid):\n{body}"


def _hand_written(solution: Solution, rng: random.Random) -> str:
    return solution.source


def _syntax_error(solution: Solution, rng: random.Random) -> str:
    source = solution.source
    return rng.choice(
        (
            source.replace("def transform(grid):", "def transform(grid)", 1),
            source.replace("return ", "return: ", 1),
            source[: source.rindex("[") + 1],
        )
    )


def _missing_transform(solution: Solution, rng: random.Random) -> str:
    name = rng.choice(("solve", "transfrom", "rule"))
    return rng.choice((_renamed(solution, name), f"{_renamed(solution, name)}\ntransform = 7\n"))


_WRONG_SHAPES = (
    "    return rule(grid)[0]\n",
    "    return []\n",
    "    return None\n",
    "    return str(rule(grid))\n",
    "    output = rule(grid)\n    output[0] = output[0] + [0]\n    return output\n",
    "    return [[0] * 31] * 31\n",
    "    return [[10 for cell in row] for row in rule(grid)]\n",
    "    return rule(grid)[:1]\n",
)


def _wrong_shape(solution: Solution, rng: random.Random) -> str:
    return _wrapped(solution, rng.choice(_WRONG_SHAPES))


_CRASHES = (
    "    return rule(grid)[99]\n",
    "    raise ValueError('no rule found')\n",
    "    return rule(grid) / 0\n",
    "    return helper(rule(grid))\n",
    "    return rule(grid)[0][0][0]\n",
)


def _crash(solution: Solution, rng: random.Random) -> str:
    return _wrapped(solution, rng.choice(_CRASHES))


def _slow(solution: Solution, rng: random.Random) -> str:
    seconds = rng.choice(SLOW_SECONDS)
    body = f"    deadline = time.monotonic() + {seconds}\n    while time.monotonic() < deadline:\n        pass\n    return rule(grid)\n"
    return _wrapped(solution, body, imports="import time\n\n")


def _memory_hungry(solution: Solution, rng: random.Random) -> str:
    mib = rng.choice(MEMORY_MIB)
    body = (
        f"    ballast = bytearray({mib} * 1024 * 1024)\n"
        "    for offset in range(0, len(ballast), 4096):\n"
        "        ballast[offset] = 1\n"
        "    return rule(grid)\n"
    )
    return _wrapped(solution, body)


def _timeout(solution: Solution, rng: random.Random) -> str:
    # At load, because the runner then gives up on every input after one per-input timeout.
    # A hang in transform costs that timeout per input, and enough inputs reach Vora's batch
    # limit, which kills the run and may cost the member.
    return f"{solution.source}\nwhile True:\n    pass\n"


_BINARY_FLIPS: Mapping[type[ast.operator], type[ast.operator]] = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Add,
    ast.FloorDiv: ast.Mod,
    ast.Mod: ast.FloorDiv,
}
_COMPARE_FLIPS: Mapping[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE,
    ast.GtE: ast.Lt,
    ast.Gt: ast.LtE,
    ast.LtE: ast.Gt,
}
_CALL_SWAPS = {"list": "sorted", "sorted": "list", "reversed": "sorted", "len": "max"}
_MUTATION_COUNTS = (1, 1, 1, 2, 2, 3)
_MUTATION_ATTEMPTS = 16


class _Mutator(ast.NodeTransformer):
    """Counts the places a program can change, and changes the one numbered ``target``."""

    def __init__(self, target: int | None, rng: random.Random) -> None:
        self.target = target
        self.rng = rng
        self.sites = 0

    def _here(self) -> bool:
        here = self.sites == self.target
        self.sites += 1
        return here

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        kind = type(node.op)
        if kind in _BINARY_FLIPS and self._here():
            node.op = _BINARY_FLIPS[kind]()
        elif kind is ast.Add and self._here():
            node.left, node.right = node.right, node.left
        return node

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        kind = type(node.ops[0])
        if kind in _COMPARE_FLIPS and self._here():
            node.ops[0] = _COMPARE_FLIPS[kind]()
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if type(node.value) is int and self._here():
            node.value = self.rng.choice([value for value in range(10) if value != node.value])
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.USub) and self._here():
            return node.operand
        return node

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.value, ast.Subscript) and self._here():
            node.slice, node.value.slice = node.value.slice, node.slice
        return node

    def visit_IfExp(self, node: ast.IfExp) -> ast.AST:
        self.generic_visit(node)
        if self._here():
            node.body, node.orelse = node.orelse, node.body
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id in _CALL_SWAPS and self._here():
            node.func.id = _CALL_SWAPS[node.func.id]
        if any(isinstance(arg, ast.Starred) for arg in node.args) and self._here():
            node.args = [arg.value if isinstance(arg, ast.Starred) else arg for arg in node.args]
        return node


def _mutated(solution: Solution, rng: random.Random) -> str:
    original = ast.unparse(ast.parse(solution.source))
    for _ in range(_MUTATION_ATTEMPTS):
        tree = ast.parse(solution.source)
        for _ in range(rng.choice(_MUTATION_COUNTS)):
            counted = _Mutator(None, rng)
            counted.visit(tree)
            if not counted.sites:
                raise ValueError(f"solution {solution.task_id} has nothing a mutation can change")
            _Mutator(rng.randrange(counted.sites), rng).visit(tree)
        mutated = ast.unparse(tree)
        if mutated != original:
            return f"{mutated}\n"
    raise ValueError(f"solution {solution.task_id}: {_MUTATION_ATTEMPTS} mutations changed nothing")


_MAKERS: Mapping[CandidateClass, Callable[[Solution, random.Random], str]] = {
    CandidateClass.HAND_WRITTEN: _hand_written,
    CandidateClass.MUTATED: _mutated,
    CandidateClass.SYNTAX_ERROR: _syntax_error,
    CandidateClass.MISSING_TRANSFORM: _missing_transform,
    CandidateClass.WRONG_SHAPE: _wrong_shape,
    CandidateClass.CRASH: _crash,
    CandidateClass.SLOW: _slow,
    CandidateClass.MEMORY_HUNGRY: _memory_hungry,
    CandidateClass.TIMEOUT: _timeout,
}
