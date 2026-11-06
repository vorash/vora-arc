"""The candidate corpus: the same inputs must give every arm the same programs, in the same order."""

from __future__ import annotations

import ast
import builtins
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from vora_arc.client import _batch_result, _Collector, batch_request
from vora_arc.corpus import (
    MIX,
    MIX_DENOMINATOR,
    SLOW_SECONDS,
    Candidate,
    CandidateClass,
    Corpus,
    Solution,
    build_corpus,
    composition,
    load_solutions,
    warmup_candidates,
)
from vora_arc.model import RunStatus, Verdict
from vora_arc.profile import load_profile
from vora_arc.tasks import load_task
from vora_arc.verify import verify

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "sandbox" / "runner.py"
TRAINING = ROOT / "data" / "arc1" / "training"
SOLUTIONS = load_solutions(ROOT / "solutions")
PER_INPUT_TIMEOUT_MS = 1000

needs_data = pytest.mark.skipif(not TRAINING.is_dir(), reason="ARC data not downloaded; run scripts/download_data.sh")


def corpus(candidates: int = 2000, seed: int = 1) -> Corpus:
    return build_corpus(SOLUTIONS, candidates, seed)


def of_class(built: Corpus, name: CandidateClass) -> list[Candidate]:
    return [candidate for candidate in built.candidates if candidate.candidate_class is name]


def test_the_same_inputs_give_the_same_candidates_in_the_same_order() -> None:
    assert corpus().candidates == corpus().candidates
    assert corpus().sha256 == corpus().sha256


def test_the_seed_changes_the_corpus() -> None:
    assert corpus(seed=1).sha256 != corpus(seed=2).sha256
    assert corpus(seed=1).candidates != corpus(seed=2).candidates


def test_a_changed_solution_changes_the_hash() -> None:
    changed = (replace(SOLUTIONS[0], source=SOLUTIONS[0].source + "\n# changed\n"), *SOLUTIONS[1:])

    assert build_corpus(changed, 200, 1).sha256 != corpus(200).sha256


@pytest.mark.parametrize("hash_seed", ["0", "1", "4242"])
def test_the_hash_does_not_depend_on_the_process(hash_seed: str) -> None:
    # Two arms are two processes, and Python randomizes str hashes per process.
    code = "from pathlib import Path\nfrom vora_arc.corpus import *\nprint(build_corpus(load_solutions(Path('solutions')), 500, 1).sha256)"
    environment = os.environ | {"PYTHONHASHSEED": hash_seed}

    printed = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=environment, capture_output=True, text=True, check=True)

    assert printed.stdout.strip() == corpus(500).sha256


def test_the_configured_mix_is_exact_at_the_experiments_size() -> None:
    assert sum(MIX.values()) == MIX_DENOMINATOR
    assert composition(MIX_DENOMINATOR) == dict(MIX)
    assert composition(2000) == {name: parts // 5 for name, parts in MIX.items()}, "five rounds of 2000 make the mix"


@pytest.mark.parametrize("candidates", [1, 6, 50, 333, 2000, 10_000])
def test_the_corpus_holds_what_its_composition_says(candidates: int) -> None:
    built = corpus(candidates)

    assert len(built.candidates) == candidates
    assert sum(built.counts.values()) == candidates
    assert Counter(candidate.candidate_class for candidate in built.candidates) == Counter(
        {name: count for name, count in built.counts.items() if count}
    )
    assert [candidate.index for candidate in built.candidates] == list(range(candidates))


def test_a_mix_that_does_not_add_up_is_refused() -> None:
    with pytest.raises(ValueError, match="adds up"):
        composition(100, {CandidateClass.HAND_WRITTEN: 1})


def test_the_expensive_classes_stay_under_one_percent_so_p99_stays_an_ordinary_programs() -> None:
    expensive = MIX[CandidateClass.SLOW] + MIX[CandidateClass.MEMORY_HUNGRY] + MIX[CandidateClass.TIMEOUT]

    assert expensive / MIX_DENOMINATOR < 0.01


def test_candidates_are_interleaved_so_no_stretch_of_the_run_is_one_class() -> None:
    first = corpus().candidates[:100]

    assert len({candidate.candidate_class for candidate in first}) >= 5


def test_every_candidate_names_a_solutions_task_and_every_task_is_used() -> None:
    tasks = {solution.task_id for solution in SOLUTIONS}

    assert {candidate.task_id for candidate in corpus().candidates} == tasks


@pytest.mark.parametrize("solution", SOLUTIONS, ids=lambda solution: solution.task_id)
def test_every_solution_can_be_mutated_into_something_else(solution: Solution) -> None:
    mutants = of_class(build_corpus([solution], 500, 1), CandidateClass.MUTATED)

    original = ast.unparse(ast.parse(solution.source))
    assert mutants and all(ast.unparse(ast.parse(mutant.program)) != original for mutant in mutants)


def test_a_solution_with_nothing_to_mutate_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="tttt0001"):
        build_corpus([Solution("tttt0001", "def transform(grid):\n    return grid\n")], 100, 1)


def test_mutants_stay_plausible_programs_with_a_transform() -> None:
    for mutant in of_class(corpus(), CandidateClass.MUTATED):
        tree = ast.parse(mutant.program)
        assert any(isinstance(node, ast.FunctionDef) and node.name == "transform" for node in tree.body)


def test_mutations_give_many_distinct_programs() -> None:
    built = corpus()

    assert built.distinct_programs[CandidateClass.MUTATED] > 200
    assert built.distinct_programs[CandidateClass.HAND_WRITTEN] == len(SOLUTIONS)


def test_a_syntax_error_candidate_really_does_not_compile() -> None:
    for candidate in of_class(corpus(), CandidateClass.SYNTAX_ERROR):
        with pytest.raises(SyntaxError):
            compile(candidate.program, "<candidate>", "exec")


def test_a_missing_transform_candidate_has_no_transform_function() -> None:
    for candidate in of_class(corpus(), CandidateClass.MISSING_TRANSFORM):
        tree = ast.parse(candidate.program)
        assert not any(isinstance(node, ast.FunctionDef) and node.name == "transform" for node in tree.body)


def test_nothing_in_the_corpus_reaches_outside_its_process() -> None:
    # Hostile programs live in the hostile suite. This corpus must be safe to measure with.
    unsafe_names = {"open", "exec", "eval", "compile", "__import__", "input", "os", "sys", "subprocess", "socket"}
    for candidate in corpus(10_000).candidates:
        if candidate.candidate_class is CandidateClass.SYNTAX_ERROR:
            continue
        tree = ast.parse(candidate.program)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert [alias.name for alias in node.names] == ["time"], candidate.program
            assert not isinstance(node, ast.ImportFrom), candidate.program
            if isinstance(node, ast.Name):
                assert node.id not in unsafe_names, candidate.program
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and hasattr(builtins, node.func.id):
                assert node.func.id not in unsafe_names, candidate.program


def test_warmup_is_hand_written_and_does_not_depend_on_the_corpus() -> None:
    warmup = warmup_candidates(SOLUTIONS, 24)

    assert len(warmup) == 24
    assert {candidate.candidate_class for candidate in warmup} == {CandidateClass.HAND_WRITTEN}
    assert {candidate.program for candidate in warmup} == {solution.source for solution in SOLUTIONS}


def verdict_from_the_real_runner(candidate: Candidate) -> Verdict:
    profile = replace(load_profile(), per_input_timeout_ms=PER_INPUT_TIMEOUT_MS)
    task = load_task(TRAINING / f"{candidate.task_id}.json")
    stdin, is_test = batch_request(profile, candidate.program, task)
    done = subprocess.run([sys.executable, str(RUNNER)], input=stdin.encode(), capture_output=True, timeout=30, check=True)
    collected = _Collector(profile, is_test)
    collected.stdout(done.stdout)
    output = collected.finish(True, "EXITED")
    assert output.done is not None, "the runner always finishes, so bench reads this as a verdict"
    result = _batch_result(
        profile,
        candidate.program,
        is_test,
        "corpus-test",
        RunStatus.COMPLETED,
        output,
        sandbox_id=None,
        startup_ms=0,
        exec_ms=0,
        peak_mem_bytes=None,
        cpu_ms=None,
    )
    return verify(task, candidate.program, result).verdict


@needs_data
@pytest.mark.parametrize(
    ("name", "allowed"),
    [
        (CandidateClass.HAND_WRITTEN, {Verdict.PASSED}),
        (CandidateClass.SYNTAX_ERROR, {Verdict.CRASHED}),
        (CandidateClass.MISSING_TRANSFORM, {Verdict.CRASHED}),
        (CandidateClass.WRONG_SHAPE, {Verdict.INVALID, Verdict.FAILED}),
        (CandidateClass.CRASH, {Verdict.CRASHED}),
        (CandidateClass.SLOW, {Verdict.PASSED}),
        (CandidateClass.MEMORY_HUNGRY, {Verdict.PASSED}),
        (CandidateClass.TIMEOUT, {Verdict.TIMEOUT}),
    ],
)
def test_each_class_earns_the_verdict_it_is_there_for_from_the_real_runner(name: CandidateClass, allowed: set[Verdict]) -> None:
    candidates = of_class(corpus(), name)
    sample = candidates[:6] if name is not CandidateClass.TIMEOUT else candidates

    assert sample
    assert {verdict_from_the_real_runner(candidate) for candidate in sample} <= allowed


@needs_data
def test_mutants_really_execute_and_mostly_fail_on_their_answer_not_on_loading() -> None:
    verdicts = Counter(verdict_from_the_real_runner(candidate) for candidate in of_class(corpus(400), CandidateClass.MUTATED)[:40])

    assert verdicts[Verdict.FAILED] > verdicts[Verdict.CRASHED], verdicts


@needs_data
def test_a_slow_candidate_stays_far_from_the_timeout_on_every_task() -> None:
    # A verdict near a limit could change with the arm's speed, and then it would say nothing about the arm.
    inputs = max(len(json.loads((TRAINING / f"{s.task_id}.json").read_text())["train"]) + 1 for s in SOLUTIONS)
    profile = load_profile()

    assert max(SLOW_SECONDS) * 1000 * 5 < profile.per_input_timeout_ms
    assert max(SLOW_SECONDS) * inputs * 2 < profile.batch_timeout_seconds
