"""`vora-arc bench` against fake pool routes, and its summary, which reads only the raw file."""

from __future__ import annotations

import base64
import json
import os
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fake_pools import ADMIN_KEY, TENANT_KEY, FakePools, Frame, Frames, Refuse, Script, stdout_frame

from vora_arc import bench, cli
from vora_arc.bench_summary import UNSAFE_LABEL, Scope, load_raw, percentiles, render_summary, summary_exit_code
from vora_arc.client import PoolMode
from vora_arc.corpus import CandidateClass, build_corpus, composition, load_solutions
from vora_arc.leak_report import WRITER_CASES, LeakReport, read_leak_suites

REVERSE = "def transform(grid):\n    return [row[::-1] for row in grid]\n"
REVERSE_AGAIN = "def transform(grid):\n    return [list(reversed(row)) for row in grid]\n"
TASK = {
    "train": [{"input": [[1, 2]], "output": [[2, 1]]}, {"input": [[3, 4]], "output": [[4, 3]]}],
    "test": [{"input": [[5, 6]], "output": [[6, 5]]}],
}
RIGHT = stdout_frame(
    {"index": 0, "status": "OK", "output": [[2, 1]], "error": None, "wall_ms": 1},
    {"index": 1, "status": "OK", "output": [[4, 3]], "error": None, "wall_ms": 1},
    {"index": 2, "status": "OK", "output": [[6, 5]], "error": None, "wall_ms": 1},
    {"done": True, "stderr_tail": ""},
)
WRONG = stdout_frame(
    {"index": 0, "status": "OK", "output": [[1, 2]], "error": None, "wall_ms": 1},
    {"index": 1, "status": "OK", "output": [[3, 4]], "error": None, "wall_ms": 1},
    {"index": 2, "status": "OK", "output": [[5, 6]], "error": None, "wall_ms": 1},
    {"done": True, "stderr_tail": ""},
)
CANDIDATES = 6
WARMUP = 2


def all_inputs(status: str) -> Frame:
    return stdout_frame(
        *[{"index": index, "status": status, "output": None, "error": status, "wall_ms": 1} for index in range(3)],
        {"done": True, "stderr_tail": ""},
    )


def answers(output: Frame, warm: bool = True) -> Frames:
    return Frames(({"run": {"warm": warm}}, output, {"exit": {"reason": "EXITED", "executionId": "exe_1"}}, {"runDone": {}}))


@dataclass
class Bench:
    fake: FakePools
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "results" / "raw.jsonl"

    def run(self, mode: str, *extra: str) -> int:
        return cli.main(
            [
                "bench",
                "--mode",
                mode,
                "--solutions",
                str(self.root / "solutions"),
                "--data-dir",
                str(self.root / "data"),
                "--raw",
                str(self.raw),
                "--candidates",
                str(CANDIDATES),
                "--warmup",
                str(WARMUP),
                "--concurrency",
                "2",
                *extra,
            ]
        )

    def rows(self, kind: str) -> list[dict[str, Any]]:
        lines = [json.loads(line) for line in self.raw.read_text().splitlines()]
        return [line for line in lines if line["type"] == kind]

    def corpus(self, candidates: int, seed: int = 1) -> dict[str, CandidateClass]:
        """The class of each program in the corpus `bench` builds with these arguments."""
        built = build_corpus(load_solutions(self.root / "solutions"), candidates, seed)
        return {candidate.program: candidate.candidate_class for candidate in built.candidates}


@pytest.fixture
def bencher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Bench]:
    split = tmp_path / "data" / "arc1" / "training"
    split.mkdir(parents=True)
    solutions = tmp_path / "solutions"
    solutions.mkdir()
    for task_id, program in (("aaaa0001", REVERSE), ("aaaa0002", REVERSE_AGAIN)):
        (split / f"{task_id}.json").write_text(json.dumps(TASK))
        (solutions / f"{task_id}.py").write_text(program)
    monkeypatch.setattr(bench, "READY_POLL_S", 0.0)
    monkeypatch.delenv("VORA_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("VORA_ARC_TENANT_ID", raising=False)
    server = FakePools()
    with server.running():
        monkeypatch.setenv("VORA_API_URL", server.url)
        monkeypatch.setenv("VORA_API_KEY", TENANT_KEY)
        yield Bench(server, tmp_path)


def use_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORA_ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setenv("VORA_ARC_TENANT_ID", "tenant-a")


def programs_by_pool(fake: FakePools) -> dict[str, list[tuple[str, str]]]:
    """Each pool's runs in the order they reached it, as (program, the inputs it was given)."""
    runs: dict[str, list[tuple[str, str]]] = {}
    for call in fake.calls("POST", "/run"):
        assert call.body is not None
        stdin = json.loads(base64.b64decode(call.body["stdin"]))
        runs.setdefault(call.path.split("/")[3], []).append((stdin["program"], json.dumps(stdin["inputs"])))
    return runs


def test_all_three_arms_run_the_same_candidates_in_the_same_order(bencher: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    use_admin(monkeypatch)
    for mode in PoolMode:
        assert bencher.run(mode.value, "--concurrency", "1", "--candidates", "40") == 0

    sequences = list(programs_by_pool(bencher.fake).values())
    assert len(sequences) == 3 and len(sequences[0]) == 40 + WARMUP
    assert sequences[0] == sequences[1] == sequences[2], "one concurrency slot, so arrival order is dispatch order"
    assert len({program for program, _ in sequences[0]}) > 10, "a corpus, not one program"

    measured = {
        header["arm"]: [
            (run["index"], run["candidate_class"], run["task"], run["program_sha256"])
            for run in bencher.rows("run")
            if run["session"] == header["session"] and run["phase"] == "measured"
        ]
        for header in bencher.rows("header")
    }
    assert measured["cold"] == measured["warm"] == measured["warm-no-reset"]
    assert [row[0] for row in measured["cold"]] == list(range(40))


def test_the_three_arms_differ_only_in_pool_shape(bencher: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    use_admin(monkeypatch)
    for mode in PoolMode:
        assert bencher.run(mode.value) == 0

    runs = bencher.fake.calls("POST", "/run")
    assert len(runs) == 3 * (CANDIDATES + WARMUP)
    per_pool: dict[str, Counter[str]] = {}
    for call in runs:
        per_pool.setdefault(call.path, Counter())[json.dumps(call.body, sort_keys=True)] += 1
    assert len(per_pool) == 3
    assert len({json.dumps(sorted(bodies.items())) for bodies in per_pool.values()}) == 1, "same programs, inputs, timeout"
    assert bencher.fake.max_in_flight <= 2, "the cold arm's extra slots don't let more programs run"

    declared = [call.body for call in bencher.fake.calls("PUT")]
    shape_keys = {"name", "size", "maxSize", "maxRuns", "reuse", "tenantId"}
    rest = {json.dumps({k: v for k, v in body.items() if k not in shape_keys}, sort_keys=True) for body in declared if body}
    assert len(rest) == 1, "the sandbox and every limit are the same"
    headers = bencher.rows("header")
    assert {header["concurrency"] for header in headers} == {2}
    assert {header["corpus_sha256"] for header in headers} == {headers[0]["corpus_sha256"]}
    assert len(bencher.fake.calls("DELETE")) == 3, "every arm gives its pool back"


def test_the_cold_arm_leaves_a_slot_for_a_destroy_still_running(bencher: Bench) -> None:
    assert bencher.run("cold") == 0

    declared = bencher.fake.calls("PUT")[0].body
    assert declared is not None
    assert (int(declared["size"]) if "size" in declared else 0, declared["maxSize"]) == (0, 4), "twice the concurrency"
    assert bencher.rows("header")[0]["pool_shape"] == {"size": 0, "max_size": 4}


def test_the_raw_file_holds_every_run_and_enough_to_rebuild_a_report(bencher: Bench) -> None:
    assert bencher.run("warm", "--image-resolved-via", "containerd", "--server-version", "v0.10.9", "--seed", "7") == 0

    header = bencher.rows("header")[0]
    assert header["arm"] == "warm"
    assert header["server_version"] == "v0.10.9"
    assert header["sdk_version"] and header["sdk_rev"], "the pinned SDK says what it is"
    assert header["git_commit"]
    assert (header["backend"], header["profile"]) == ("gvisor", "python-arc")
    assert header["cpu_count"] and len(header["load_start"]) == 3
    assert (header["concurrency"], header["warmup"], header["candidates"]) == (2, WARMUP, CANDIDATES)
    assert header["image_resolved_via"] == "containerd"
    built = build_corpus(load_solutions(bencher.root / "solutions"), CANDIDATES, 7)
    assert header["corpus_seed"] == 7
    assert header["corpus_sha256"] == built.sha256
    assert header["corpus_counts"] == {name.value: count for name, count in composition(CANDIDATES).items()}
    assert header["corpus_mix"] == {name.value: parts for name, parts in built.mix.items()}
    assert header["corpus_distinct_programs"] == {name.value: n for name, n in built.distinct_programs.items()}
    footer = bencher.rows("footer")[0]
    assert footer["completed"] is True
    assert len(footer["load_end"]) == 3
    assert footer["measured_seconds"] > 0

    runs = bencher.rows("run")
    assert [run["phase"] for run in runs].count("warmup") == WARMUP
    measured = [run for run in runs if run["phase"] == "measured"]
    assert sorted(run["index"] for run in measured) == list(range(CANDIDATES))
    by_index = {candidate.index: candidate for candidate in built.candidates}
    for run in measured:
        candidate = by_index[run["index"]]
        assert (run["candidate_class"], run["task"]) == (candidate.candidate_class.value, candidate.task_id)
        assert run["program_sha256"] == candidate.program_sha256
    run = runs[-1]
    assert run["arm"] == "warm"
    assert run["wall_ms"] > 0 and run["exec_ms"] >= 0 and run["cycle_ms"] >= run["wall_ms"]
    assert run["warm"] is True
    assert run["startup_ms"] == 1
    assert run["reset_ms"] == 3
    assert run["audit_log_id"].startswith("exe_")
    assert run["exit_reason"] == "EXITED"
    assert run["verdict"] == "passed", "this fake answers every program correctly"
    assert run["infra_failure"] is None


def test_warmup_runs_only_known_good_programs_and_stays_out_of_the_corpus(bencher: Bench) -> None:
    assert bencher.run("warm") == 0

    warmup = [run for run in bencher.rows("run") if run["phase"] == "warmup"]
    assert {run["candidate_class"] for run in warmup} == {"hand_written"}
    assert load_raw(bencher.raw).arms[0].measured == CANDIDATES


def test_an_infrastructure_failure_is_counted_and_makes_the_command_fail(
    bencher: Bench, capsys: pytest.CaptureFixture[str]
) -> None:
    bencher.fake.starting_polls = 0
    bencher.fake.runs.extend(
        [
            answers(RIGHT),
            answers(RIGHT),
            Refuse(429, "pool full"),
            Frames(({"run": {"warm": True, "sandboxId": "s"}}, {"error": {"code": "run_failed", "message": "gone"}})),
            Frames(({"run": {"warm": True}}, RIGHT, {"exit": {"reason": "RUNTIME_FAILURE"}}, {"runDone": {}})),
        ]
    )

    assert bencher.run("warm") == 1, "Vora failing makes the command say so"

    summary = load_raw(bencher.raw).arms[0]
    assert summary.measured == CANDIDATES
    assert summary.infra_failed == 3
    assert summary.judged == 3
    assert summary.infra_failures == {"RateLimitedError": 1, "run_failed": 1, "exit_reason:RUNTIME_FAILURE": 1}
    assert summary.wall.count == 3, "a refusal is fast, so it stays out of the latencies and shows in the count"
    assert "3 infrastructure failures" in capsys.readouterr().out
    assert len(bencher.fake.calls("POST", "/run")) == CANDIDATES + WARMUP, "a bench run is never retried"


def test_an_infrastructure_failure_has_no_verdict_and_never_counts_as_one(bencher: Bench) -> None:
    bencher.fake.runs.extend([answers(RIGHT), answers(RIGHT), Refuse(429, "pool full")])

    bencher.run("warm", "--concurrency", "1")

    refused = next(run for run in bencher.rows("run") if run["infra_failure"] == "RateLimitedError")
    assert refused["verdict"] is None
    summary = load_raw(bencher.raw).arms[0]
    assert sum(summary.verdicts.values()) == CANDIDATES - 1, "the refusal is in no verdict's count"
    assert summary.programs_per_second is not None and summary.footer is not None
    assert summary.footer.measured_seconds is not None
    assert summary.programs_per_second == pytest.approx((CANDIDATES - 1) / summary.footer.measured_seconds)


def test_a_completed_run_with_no_answer_from_the_runner_is_an_infrastructure_failure(bencher: Bench) -> None:
    # A broken image exits cleanly with no output. Called "crashed", it would be a fast verdict that flatters the arm.
    silent = Frames(({"run": {"warm": True}}, {"exit": {"reason": "EXITED", "exitCode": 2}}, {"runDone": {}}))
    bencher.fake.runs.extend([answers(RIGHT), answers(RIGHT), silent])

    assert bencher.run("warm") == 1

    summary = load_raw(bencher.raw).arms[0]
    assert summary.infra_failures == {"no_runner_result": 1}


def judged_by_class(classes: dict[str, CandidateClass]) -> Any:
    """Each junk class gets the answer it earns from a real runner, and the rest get the right one."""
    outputs: dict[CandidateClass, Frame] = {
        CandidateClass.MUTATED: WRONG,
        CandidateClass.SYNTAX_ERROR: all_inputs("ERROR"),
        CandidateClass.MISSING_TRANSFORM: all_inputs("ERROR"),
        CandidateClass.CRASH: all_inputs("ERROR"),
        CandidateClass.WRONG_SHAPE: all_inputs("INVALID"),
        CandidateClass.TIMEOUT: all_inputs("TIMEOUT"),
    }

    def script(pool: str, program: str) -> Script | None:
        name = classes.get(program)
        return answers(outputs[name], warm="cold" not in pool) if name in outputs else None

    return script


def test_junk_failing_verification_is_a_verdict_and_the_command_succeeds(bencher: Bench) -> None:
    bencher.fake.script_for = judged_by_class(bencher.corpus(1000))

    assert bencher.run("warm", "--candidates", "1000") == 0, "a junk program failing is the expected result"

    summary = load_raw(bencher.raw).arms[0]
    assert (summary.infra_failed, summary.off_shape) == (0, 0)
    assert summary.judged == 1000
    assert summary.wall.count == 1000, "a junk run is part of what the arm costs"
    by_class = {row.name: row.verdicts for row in summary.classes}
    assert by_class["mutated"] == {"failed": 501}
    assert by_class["syntax_error"] == {"crashed": 100}
    assert by_class["missing_transform"] == {"crashed": 50}
    assert by_class["crash"] == {"crashed": 120}
    assert by_class["wrong_shape"] == {"invalid": 120}
    assert by_class["timeout"] == {"timeout": 1}
    assert by_class["hand_written"] == {"passed": 100}


def test_a_hand_written_solution_not_passing_says_the_arm_is_broken_with_only_one_arm_to_look_at(
    bencher: Bench, capsys: pytest.CaptureFixture[str]
) -> None:
    # Every program crashing fast would otherwise read as a very fast arm with no failures.
    bencher.fake.script_for = lambda pool, program: answers(all_inputs("ERROR"))

    assert bencher.run("warm", "--warmup", "0") == 1

    summary = load_raw(bencher.raw).arms[0]
    assert summary.broken
    assert summary.infra_failed == 0
    assert len(summary.hand_written_not_passed) == composition(CANDIDATES)[CandidateClass.HAND_WRITTEN]
    printed = capsys.readouterr().out
    assert "hand-written solutions did not pass" in printed and "this arm is broken" in printed
    assert "this arm is broken" in render_summary(load_raw(bencher.raw))


def test_a_hand_written_solution_not_passing_on_the_no_reset_arm_is_a_finding(
    bencher: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_admin(monkeypatch)
    unsafe = {"run": {"warm": True, "reuse": "POOL_REUSE_UNSAFE_NO_RESET"}}
    wrong = Frames((unsafe, WRONG, {"exit": {"reason": "EXITED"}}, {"runDone": {}}))
    bencher.fake.script_for = lambda pool, program: wrong

    assert bencher.run("warm-no-reset", "--warmup", "0") == 0

    summary = load_raw(bencher.raw).arms[0]
    assert summary.hand_written_not_passed and not summary.broken
    text = render_summary(load_raw(bencher.raw))
    assert "that is a finding" in text and "this arm is broken" not in text


def only_on_arm(arm: str, program: str, output: Frame) -> Any:
    reuse = {"reuse": "POOL_REUSE_UNSAFE_NO_RESET"} if arm == "warm-no-reset" else {}

    def script(pool: str, seen: str) -> Script | None:
        if seen != program or not pool.startswith(f"vora-arc-bench-{arm}-"):
            return None
        return Frames(({"run": {"warm": arm != "cold"} | reuse}, output, {"exit": {"reason": "EXITED"}}, {"runDone": {}}))

    return script


def a_mutant(bencher: Bench, candidates: int = 40) -> str:
    return next(program for program, name in bencher.corpus(candidates).items() if name is CandidateClass.MUTATED)


def test_a_verdict_that_differs_between_cold_and_warm_is_reported_prominently(
    bencher: Bench, capsys: pytest.CaptureFixture[str]
) -> None:
    mutant = a_mutant(bencher)
    bencher.fake.script_for = only_on_arm("warm", mutant, all_inputs("ERROR"))
    assert bencher.run("cold", "--candidates", "40") == 0
    assert bencher.run("warm", "--candidates", "40") == 0
    capsys.readouterr()

    raw = load_raw(bencher.raw)
    (comparison,) = raw.comparisons
    (disagreement,) = comparison.disagreements
    assert disagreement.scope is Scope.SAFE_ARMS
    assert disagreement.verdicts == {"cold": {"passed": 1}, "warm": {"crashed": 1}}
    assert disagreement.program_sha256 == next(
        run["program_sha256"] for run in bencher.rows("run") if run["index"] == disagreement.index and run["phase"] == "measured"
    )
    text = render_summary(raw)
    head = text[: text.index("| Arm | Sessions")]
    assert "**1 candidates differ on arms that must agree, in their verdict or their outputs." in head, "before any latency"
    assert f"| {disagreement.index} | mutated |" in head
    assert "passed x1" in head and "crashed x1" in head


def test_verdicts_are_compared_across_raw_files(bencher: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    mutant = a_mutant(bencher)
    bencher.fake.script_for = only_on_arm("warm", mutant, all_inputs("ERROR"))
    assert bencher.run("cold", "--candidates", "40", "--raw", str(bencher.root / "cold.jsonl")) == 0
    assert bencher.run("warm", "--candidates", "40", "--raw", str(bencher.root / "warm.jsonl")) == 0
    capsys.readouterr()

    assert cli.main(["bench-summary", str(bencher.root / "cold.jsonl"), str(bencher.root / "warm.jsonl")]) == 1

    assert "**1 candidates differ on arms that must agree" in capsys.readouterr().out


def test_a_verdict_that_differs_only_on_the_no_reset_arm_is_a_finding_not_an_error(
    bencher: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_admin(monkeypatch)
    mutant = a_mutant(bencher)
    bencher.fake.script_for = only_on_arm("warm-no-reset", mutant, all_inputs("ERROR"))
    for mode in PoolMode:
        assert bencher.run(mode.value, "--candidates", "40") == 0, "a finding doesn't fail the run"

    raw = load_raw(bencher.raw)
    (comparison,) = raw.comparisons
    (disagreement,) = comparison.disagreements
    assert disagreement.scope is Scope.NO_RESET
    text = render_summary(raw)
    assert "differ only where the unsafe no-reset arm is involved" in text and "This is a finding" in text
    assert "arms that must agree" not in text
    assert summary_exit_code(raw, []) == 0, "a finding about the unsafe arm doesn't fail the summary"


def wrong_but_different(program: str, arm: str) -> Any:
    """On this arm the program still fails verification, with a different wrong answer."""
    other_wrong = stdout_frame(
        {"index": 0, "status": "OK", "output": [[7, 7]], "error": None, "wall_ms": 1},
        {"index": 1, "status": "OK", "output": [[7, 7]], "error": None, "wall_ms": 1},
        {"index": 2, "status": "OK", "output": [[7, 7]], "error": None, "wall_ms": 1},
        {"done": True, "stderr_tail": ""},
    )

    def script(pool: str, seen: str) -> Script | None:
        if seen != program:
            return None
        output = other_wrong if pool.startswith(f"vora-arc-bench-{arm}-") else WRONG
        reuse = {"reuse": "POOL_REUSE_UNSAFE_NO_RESET"} if "no-reset" in pool else {}
        return Frames(({"run": {"warm": "cold" not in pool} | reuse}, output, {"exit": {"reason": "EXITED"}}, {"runDone": {}}))

    return script


def test_a_wrong_answer_that_changes_between_safe_arms_fails_the_summary_though_both_say_failed(
    bencher: Bench, capsys: pytest.CaptureFixture[str]
) -> None:
    # Half the corpus is expected to fail, so a leak that changes a wrong answer never shows in a verdict.
    bencher.fake.script_for = wrong_but_different(a_mutant(bencher), "warm")
    assert bencher.run("cold", "--candidates", "40") == 0
    assert bencher.run("warm", "--candidates", "40") == 0
    capsys.readouterr()

    assert cli.main(["bench-summary", str(bencher.raw)]) == 1

    (comparison,) = load_raw(bencher.raw).comparisons
    (item,) = comparison.disagreements
    assert (item.scope, item.verdict_differs, item.output_differs) == (Scope.SAFE_ARMS, False, True)
    assert item.verdicts == {"cold": {"failed": 1}, "warm": {"failed": 1}}
    assert item.outputs["cold"] != item.outputs["warm"]
    printed = capsys.readouterr().out
    head = printed[: printed.index("| Arm | Sessions")]
    assert "**1 candidates differ on arms that must agree" in head, "before any latency"
    assert f"| {item.index} | mutated |" in head
    assert "| outputs |" in head


def test_a_wrong_answer_that_changes_only_on_no_reset_is_a_finding_and_exits_0(
    bencher: Bench, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_admin(monkeypatch)
    bencher.fake.script_for = wrong_but_different(a_mutant(bencher), "warm-no-reset")
    for mode in PoolMode:
        assert bencher.run(mode.value, "--candidates", "40") == 0
    capsys.readouterr()

    assert cli.main(["bench-summary", str(bencher.raw)]) == 0

    (comparison,) = load_raw(bencher.raw).comparisons
    (item,) = comparison.disagreements
    assert (item.scope, item.verdict_differs, item.output_differs) == (Scope.NO_RESET, False, True)
    assert "With the no-reset arm:" in capsys.readouterr().out


def test_no_reset_differing_from_cold_with_warm_missing_does_not_claim_the_safe_arms_agree(
    bencher: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_admin(monkeypatch)
    bencher.fake.script_for = only_on_arm("warm-no-reset", a_mutant(bencher), all_inputs("ERROR"))
    assert bencher.run("cold", "--candidates", "40") == 0
    assert bencher.run("warm-no-reset", "--candidates", "40") == 0

    raw = load_raw(bencher.raw)
    (comparison,) = raw.comparisons
    (item,) = comparison.disagreements

    assert item.scope is Scope.NO_RESET_UNCHECKED
    assert summary_exit_code(raw, []) == 0
    assert "no-reset, with a safe arm's result missing" in render_summary(raw)


def test_a_hand_written_failure_on_a_safe_arm_fails_the_summary_and_on_no_reset_does_not(
    bencher: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_admin(monkeypatch)
    bencher.fake.script_for = lambda pool, program: answers(all_inputs("ERROR"), warm=False)
    assert bencher.run("cold", "--warmup", "0") == 1
    assert summary_exit_code(load_raw(bencher.raw), []) == 1

    other = bencher.root / "no-reset.jsonl"
    unsafe = {"run": {"warm": True, "reuse": "POOL_REUSE_UNSAFE_NO_RESET"}}
    bencher.fake.script_for = lambda pool, program: Frames((unsafe, WRONG, {"exit": {"reason": "EXITED"}}, {"runDone": {}}))
    assert bencher.run("warm-no-reset", "--warmup", "0", "--raw", str(other)) == 0
    assert summary_exit_code(load_raw(other), []) == 0


def test_a_summary_exits_0_on_incomplete_or_not_run_leak_suites_and_1_on_a_failed_one(bencher: Bench) -> None:
    assert bencher.run("warm") == 0
    raw = load_raw(bencher.raw)
    report = bencher.root / "vora.log"

    assert summary_exit_code(raw, read_leak_suites()) == 0, "not run, and printed loudly"

    report.write_text("--- PASS: TestLeakMatrixGvisor (1.00s)\nPASS\nok  \tvora\t1.0s\n")
    suites = read_leak_suites(vora_reports=[LeakReport("gvisor", report)])
    assert any(suite.status.startswith("incomplete") for suite in suites)
    assert summary_exit_code(raw, suites) == 0, "a partial summary is still useful"

    report.write_text("--- FAIL: TestLeakMatrixGvisor (1.00s)\nFAIL\n")
    assert summary_exit_code(raw, read_leak_suites(vora_reports=[LeakReport("gvisor", report)])) == 1


def test_arms_that_agree_say_how_many_candidates_they_compared(bencher: Bench) -> None:
    assert bencher.run("cold") == 0
    assert bencher.run("warm") == 0

    text = render_summary(load_raw(bencher.raw))

    assert f"The {CANDIDATES} candidates compared got the same verdict and outputs" in text
    assert "Corpus seed 1 ran only on cold, warm." in text


def test_one_arm_alone_has_nothing_to_compare_and_says_so(bencher: Bench) -> None:
    assert bencher.run("warm") == 0

    text = render_summary(load_raw(bencher.raw))

    assert "The 0 candidates compared" in text
    assert f"Corpus seed 1: {CANDIDATES} candidates aren't compared" in text


def test_a_refused_run_on_one_arm_is_not_a_disagreement(bencher: Bench) -> None:
    assert bencher.run("cold", "--concurrency", "1") == 0
    bencher.fake.runs.extend([answers(RIGHT), answers(RIGHT), Refuse(429, "pool full")])
    assert bencher.run("warm", "--concurrency", "1") == 1

    (comparison,) = load_raw(bencher.raw).comparisons

    assert comparison.disagreements == ()
    assert (comparison.compared, comparison.uncompared, comparison.infra_failed) == (CANDIDATES - 1, 1, 1)


def test_a_candidate_with_a_failure_on_one_arm_is_not_compared_however_many_runs_it_has(bencher: Bench) -> None:
    for _ in range(2):
        assert bencher.run("cold", "--concurrency", "1") == 0
    bencher.fake.runs.extend([answers(RIGHT), answers(RIGHT), Refuse(429, "pool full")])
    assert bencher.run("warm", "--concurrency", "1") == 1

    (comparison,) = load_raw(bencher.raw).comparisons

    assert (comparison.compared, comparison.uncompared, comparison.infra_failed) == (CANDIDATES - 1, 1, 1)


def test_programs_per_second_comes_from_the_measured_window_and_leaves_warmup_out(bencher: Bench) -> None:
    slow_warmup = 0.5
    right = answers(RIGHT)
    bencher.fake.runs.extend([Frames(right.frames, delay_s=slow_warmup)] * WARMUP)

    assert bencher.run("warm", "--concurrency", "1") == 0

    summary = load_raw(bencher.raw).arms[0]
    assert summary.footer is not None and summary.footer.measured_seconds is not None
    assert summary.footer.measured_seconds < slow_warmup, "the slow warmup isn't in the window"
    assert summary.programs_per_second == pytest.approx(CANDIDATES / summary.footer.measured_seconds)

    rows = [json.loads(line) for line in bencher.raw.read_text().splitlines()]
    for row in rows:
        if row["type"] == "footer":
            row["measured_seconds"] = 2.0
    bencher.raw.write_text("".join(json.dumps(row) + "\n" for row in rows))
    text = render_summary(load_raw(bencher.raw))
    assert load_raw(bencher.raw).arms[0].programs_per_second == pytest.approx(CANDIDATES / 2.0), "rebuilt from the file"
    assert f"{CANDIDATES / 2.0:.1f}, {CANDIDATES} verdicts over 2.0 s of measured wall time at concurrency 1" in text


def test_latency_is_reported_overall_and_per_class_and_a_timeout_can_be_read_apart(bencher: Bench) -> None:
    assert bencher.run("warm", "--candidates", "40") == 0
    rows = [json.loads(line) for line in bencher.raw.read_text().splitlines()]
    measured = [row for row in rows if row["type"] == "run" and row["phase"] == "measured"]
    slow = measured[0]
    slow["candidate_class"] = "timeout"
    slow["wall_ms"] = 10_000.0
    bencher.raw.write_text("".join(json.dumps(row) + "\n" for row in rows))

    summary = load_raw(bencher.raw).arms[0]

    assert summary.wall.max == 10_000.0, "the overall row keeps it"
    assert summary.wall_without_timeouts.max is not None and summary.wall_without_timeouts.max < 10_000.0
    assert summary.wall_without_timeouts.count == 39
    timeouts = next(row for row in summary.classes if row.name == "timeout")
    assert (timeouts.judged, timeouts.wall.p50, timeouts.wall.p99, timeouts.wall.max) == (1, 10_000.0, 10_000.0, 10_000.0)
    text = render_summary(load_raw(bencher.raw))
    for name in CandidateClass:
        assert f"| {name.value} | " in text
    assert "| All but timeout | " in text
    assert sum(row.slot_share or 0 for row in summary.classes) > 0


def test_the_corpus_composition_is_in_every_summary(bencher: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    assert bencher.run("warm", "--candidates", "2000", "--concurrency", "4", "--seed", "3") == 0

    printed = capsys.readouterr().out
    for text in (printed, render_summary(load_raw(bencher.raw))):
        assert "seed 3, sha256 " in text
        assert "hand_written 200 (10.00%," in text
        assert "mutated 1002 (50.10%," in text
        assert "timeout 2 (0.10%," in text


def test_a_warm_arm_counts_a_run_that_was_not_warm(bencher: Bench) -> None:
    warm, cold = answers(RIGHT), answers(RIGHT, warm=False)
    bencher.fake.runs.extend([warm, warm, cold, warm, warm, warm, warm, warm])

    assert bencher.run("warm") == 1

    summary = load_raw(bencher.raw).arms[0]
    assert (summary.warm, summary.cold, summary.off_shape) == (5, 1, 1)
    assert summary.infra_failed == 0, "it ran fine, and stays in the latencies"
    assert summary.wall.count == 6


def test_a_healthy_warm_session_with_retirements_exits_0_and_shows_why(bencher: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    # At concurrency 1 nothing else is in flight, so Vora's next borrower starts cold after every retirement.
    bencher.fake.destroy_s = 0.01

    assert bencher.run("warm", "--concurrency", "1", "--candidates", "250") == 0

    summary = load_raw(bencher.raw).arms[0]
    assert summary.off_shape_bound == 252 // 100
    assert summary.off_shape == 2, "one cold run per retirement"
    assert summary.retire_causes == {"max_runs": 2}
    assert (summary.sandboxes, summary.longest_sandbox_run) == (3, 100)
    assert summary.wall.count == summary.judged == 250, "a cold run stays in the arm's numbers"
    printed = capsys.readouterr().out
    assert "not what this arm requires: 2 of 250 (0.8%), against a bound of 2" in printed
    assert "Retired at check-in: {'max_runs': 2}. 3 sandboxes, 2 first runs, longest sandbox 100 runs" in printed


def test_a_warm_session_with_runs_in_flight_gets_replacements_instead_of_cold_starts(bencher: Bench) -> None:
    assert bencher.run("warm", "--concurrency", "2", "--candidates", "400") == 0

    summary = load_raw(bencher.raw).arms[0]
    assert summary.retire_causes["max_runs"] >= 3
    assert summary.off_shape <= summary.off_shape_bound
    assert summary.sandboxes > 2, "each member has its own id"


def test_the_no_reset_arm_gets_the_same_bound(bencher: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    use_admin(monkeypatch)
    bencher.fake.destroy_s = 0.01

    assert bencher.run("warm-no-reset", "--concurrency", "1", "--candidates", "150") == 0

    summary = load_raw(bencher.raw).arms[0]
    assert (summary.off_shape, summary.off_shape_bound) == (1, 1)


def cold_answers_up_to(count: int) -> Any:
    """Every run is right, and the first ``count`` that reach the fake start cold."""
    seen = iter(range(10**6))

    def script(pool: str, program: str) -> Script | None:
        return answers(RIGHT, warm=next(seen) >= count)

    return script


def test_a_cold_run_above_the_bound_fails_the_arm_and_at_the_bound_does_not(bencher: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    arguments = ("--warmup", "0", "--candidates", "200")

    bencher.fake.script_for = cold_answers_up_to(2)
    assert bencher.run("warm", *arguments) == 0

    bencher.fake.script_for = cold_answers_up_to(3)
    assert bencher.run("warm", *arguments) == 1

    above = load_raw(bencher.raw).arms[1]
    assert (above.off_shape, above.off_shape_bound, above.failed) == (3, 2, True)
    assert "above the bound of 2 that retirements explain, so this arm is broken" in capsys.readouterr().out


def test_a_warm_arm_that_really_runs_cold_exits_1(bencher: Bench) -> None:
    bencher.fake.script_for = lambda pool, program: answers(RIGHT, warm=False)

    assert bencher.run("warm", "--candidates", "300", "--warmup", "0") == 1

    summary = load_raw(bencher.raw).arms[0]
    assert (summary.warm, summary.cold, summary.off_shape_bound) == (0, 300, 3)


def test_a_session_longer_than_max_age_gets_room_for_those_retirements_too(bencher: Bench) -> None:
    assert bencher.run("warm") == 0
    rows = [json.loads(line) for line in bencher.raw.read_text().splitlines()]
    for row in rows:
        if row["type"] == "footer":
            row["measured_seconds"] = 3700.0
    bencher.raw.write_text("".join(json.dumps(row) + "\n" for row in rows))

    assert load_raw(bencher.raw).arms[0].off_shape_bound == 2 * 2, "two max_age periods at concurrency 2, and no max_runs retirement"


def test_a_cold_run_on_a_warm_arm_stays_in_its_latencies(bencher: Bench) -> None:
    bencher.fake.script_for = cold_answers_up_to(1)
    assert bencher.run("warm", "--warmup", "0", "--candidates", "200") == 0
    rows = [json.loads(line) for line in bencher.raw.read_text().splitlines()]
    for row in rows:
        if row["type"] == "run" and row["warm"] is False:
            row["wall_ms"] = 99_999.0
    bencher.raw.write_text("".join(json.dumps(row) + "\n" for row in rows))

    summary = load_raw(bencher.raw).arms[0]
    assert (summary.cold, summary.wall.max) == (1, 99_999.0), "leaving it out would flatter the arm"


def test_the_cold_arm_counts_a_run_that_was_warm(bencher: Bench) -> None:
    bencher.fake.runs.extend([answers(RIGHT)] * 3)

    assert bencher.run("cold") == 1

    summary = load_raw(bencher.raw).arms[0]
    assert summary.off_shape == 1, "the first two went to warmup"
    assert summary.cold == 5


def test_a_warm_arm_that_got_an_unsafe_member_says_so(bencher: Bench) -> None:
    unsafe = {"run": {"warm": True, "reuse": "POOL_REUSE_UNSAFE_NO_RESET"}}
    bencher.fake.runs.extend([Frames((unsafe, RIGHT, {"exit": {"reason": "EXITED"}}, {"runDone": {}}))] * 3)

    assert bencher.run("warm") == 1

    assert load_raw(bencher.raw).arms[0].wrong_reuse == 1


def test_what_vora_left_out_is_null_in_the_raw_file_and_not_in_the_percentiles(bencher: Bench) -> None:
    assert bencher.run("cold") == 0

    runs = [run for run in bencher.rows("run") if run["phase"] == "measured"]
    assert {run["reset_ms"] for run in runs} == {None}, "a retired member had no reset, which isn't a reset of 0"
    summary = load_raw(bencher.raw).arms[0]
    assert (summary.reset.count, summary.reset.missing, summary.reset.p50) == (0, 6, None)
    assert "| This run's reset (Vora) | 0 | 6 | not measured | not measured | not measured | not measured |" in render_summary(
        load_raw(bencher.raw)
    )


def test_the_no_reset_arm_labels_itself_unsafe_everywhere_it_speaks(
    bencher: Bench, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_admin(monkeypatch)
    assert bencher.run("warm-no-reset") == 0

    printed = capsys.readouterr().out
    assert printed.splitlines()[0] == f"arm: warm-no-reset ({UNSAFE_LABEL})", "the first thing it says"
    assert f"## warm-no-reset ({UNSAFE_LABEL})" in printed
    assert bencher.rows("header")[0]["unsafe"] is True
    summary = render_summary(load_raw(bencher.raw))
    assert f"| warm-no-reset ({UNSAFE_LABEL}) |" in summary
    assert f"## warm-no-reset ({UNSAFE_LABEL})" in summary


def test_the_safe_arms_are_not_labelled_unsafe(bencher: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    assert bencher.run("warm") == 0
    assert bencher.run("cold") == 0

    assert "UNSAFE" not in capsys.readouterr().out
    assert "UNSAFE" not in render_summary(load_raw(bencher.raw))
    assert {header["unsafe"] for header in bencher.rows("header")} == {False}


def test_the_no_reset_arm_goes_through_the_admin_gate(bencher: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit, match="VORA_ADMIN_API_KEY"):
        bencher.run("warm-no-reset")
    assert bencher.fake.calls("PUT") == []
    assert bencher.rows("footer")[0]["completed"] is False, "the raw file says the arm didn't finish"

    use_admin(monkeypatch)
    assert bencher.run("warm-no-reset") == 0
    declare = bencher.fake.calls("PUT")[0]
    assert declare.key == ADMIN_KEY
    assert {call.key for call in bencher.fake.calls("POST", "/run")} == {TENANT_KEY}


def test_warm_runs_wait_for_the_pool_to_fill(bencher: Bench) -> None:
    bencher.fake.starting_polls = 3

    assert bencher.run("warm") == 0

    polled = bencher.fake.calls("GET", "/vora-arc-bench-warm-" + bencher.rows("header")[0]["session"])
    assert len(polled) == 3, "the declare's answer used up the first of the three"
    assert bencher.fake.seen.index(polled[-1]) < bencher.fake.seen.index(bencher.fake.calls("POST", "/run")[0])
    assert bencher.rows("footer")[0]["pool_ready_ms"] is not None


def test_a_pool_that_never_fills_ends_the_arm_and_gives_it_back(bencher: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench, "READY_TIMEOUT_S", 0.0)
    bencher.fake.starting_polls = 1000

    with pytest.raises(SystemExit, match="did not reach 2 idle"):
        bencher.run("warm")

    assert bencher.fake.calls("POST", "/run") == []
    assert len(bencher.fake.calls("DELETE")) == 1


def test_the_server_version_comes_from_the_admin_route_or_says_why_not(
    bencher: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert bencher.run("warm") == 0
    header = bencher.rows("header")[0]
    assert header["server_version"] is None
    assert "VORA_ADMIN_API_KEY" in header["server_version_source"]

    use_admin(monkeypatch)
    assert bencher.run("warm") == 0
    assert bencher.rows("header")[1]["server_version"] == "0.10.9"


def test_an_unconfirmed_image_source_is_said_out_loud(bencher: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    assert bencher.run("cold") == 0

    assert "image resolved via: unconfirmed" in capsys.readouterr().out
    assert "vorash/vora#148" in render_summary(load_raw(bencher.raw))


def test_a_busy_machine_is_said_out_loud(
    bencher: Bench, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(os, "getloadavg", lambda: (1000.0, 1000.0, 1000.0))

    assert bencher.run("cold") == 0

    assert "warning: this machine was busy" in capsys.readouterr().out
    assert "this machine was busy" in render_summary(load_raw(bencher.raw))


def test_a_summary_rebuilds_from_the_raw_file_with_no_server(bencher: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    assert bencher.run("warm") == 0
    live = capsys.readouterr().out
    bencher.fake.seen.clear()

    assert cli.main(["bench-summary", str(bencher.raw)]) == 0

    rebuilt = capsys.readouterr().out
    assert bencher.fake.seen == []
    section = rebuilt[rebuilt.index("## warm"):].strip()
    assert section in live, "the summary printed after a run is the one the file rebuilds"


def test_warmup_is_left_out_of_every_measured_number(bencher: Bench) -> None:
    assert bencher.run("warm") == 0
    lines = bencher.raw.read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    for row in rows:
        if row["type"] == "run" and row["phase"] == "warmup":
            row["wall_ms"] = 999999.0
    bencher.raw.write_text("".join(json.dumps(row) + "\n" for row in rows))

    summary = load_raw(bencher.raw).arms[0]
    assert summary.wall.max is not None and summary.wall.max < 999999.0
    assert (summary.warmup, summary.measured) == (2, 6)


def test_a_line_cut_short_by_a_kill_is_counted_and_the_rest_still_reads(bencher: Bench) -> None:
    assert bencher.run("warm") == 0
    with bencher.raw.open("a") as file:
        file.write('{"type": "run", "session": "abc')

    raw = load_raw(bencher.raw)

    assert raw.unreadable_lines == 1
    assert raw.arms[0].measured == 6
    assert "1 lines of this file could not be read" in render_summary(raw)


def test_an_arm_with_no_footer_says_it_did_not_finish(bencher: Bench) -> None:
    assert bencher.run("warm") == 0
    kept = [line for line in bencher.raw.read_text().splitlines() if json.loads(line)["type"] != "footer"]
    bencher.raw.write_text("\n".join(kept) + "\n")

    text = render_summary(load_raw(bencher.raw))

    assert "This arm did not finish" in text
    assert "Programs per second: not measured" in text


def test_sessions_of_an_arm_show_their_median_and_range_and_too_few_are_called_out(bencher: Bench) -> None:
    for _ in range(2):
        assert bencher.run("warm") == 0

    text = render_summary(load_raw(bencher.raw))

    assert "| warm | 2 | " in text
    assert "warm has 2 sessions: fewer than 5 can't show it reproduces." in text


def test_arms_that_ran_different_corpora_are_not_compared_silently(bencher: Bench) -> None:
    assert bencher.run("warm", "--seed", "1") == 0
    assert bencher.run("cold", "--seed", "2") == 0

    text = render_summary(load_raw(bencher.raw))

    assert "These arms ran different corpora, so the arms are not comparable." in text
    assert all(comparison.compared == 0 for comparison in load_raw(bencher.raw).comparisons)


def test_the_summary_records_the_order_the_sessions_ran_in(bencher: Bench) -> None:
    assert bencher.run("warm") == 0
    assert bencher.run("cold") == 0

    assert "Session order: warm, cold." in render_summary(load_raw(bencher.raw))


def test_leak_results_show_not_run_without_a_report(bencher: Bench) -> None:
    assert bencher.run("warm") == 0

    text = render_summary(load_raw(bencher.raw))

    assert "## Leak tests" in text
    assert text.count("| not run | 0 | 0 | 0 | none given |") == 3


def test_leak_results_come_from_the_reports_given_to_the_summary(bencher: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    assert bencher.run("warm") == 0
    capsys.readouterr()
    pytest_report = bencher.root / "leak.xml"
    pytest_report.write_text(
        '<testsuites><testsuite>'
        + "".join(f'<testcase name="test_a_write_does_not_survive_into_the_next_run[{case}]"/>' for case in WRITER_CASES)
        + '<testcase name="test_without_a_reset_the_same_write_does_survive[write_workspace-0]"><skipped/></testcase>'
        "</testsuite></testsuites>"
    )
    vora_report = bencher.root / "vora.log"
    vora_report.write_text("--- FAIL: TestLeakMatrixGvisor (1.00s)\n")

    args = ["bench-summary", str(bencher.raw), "--leak-pytest", f"gvisor={pytest_report}", "--leak-vora", f"gvisor={vora_report}"]
    assert cli.main(args) == 1, "a failed leak suite"

    printed = capsys.readouterr().out
    assert f"| gvisor | passed | 3 | 0 | 0 | {pytest_report}, written " in printed
    assert "| gvisor | incomplete: missing " in printed and "skipped test_without_a_reset_the_same_write_does_survive" in printed
    assert f"| gvisor | FAILED | 0 | 1 | 0 | {vora_report}, written " in printed
    assert "**2 of 3 leak suites did not pass." in printed


def test_a_leak_report_older_than_the_sessions_is_flagged_next_to_them(bencher: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    assert bencher.run("warm") == 0
    capsys.readouterr()
    report = bencher.root / "vora.log"
    report.write_text(
        "--- PASS: TestLeakMatrixGvisor (1.00s)\n    --- PASS: TestPoolLeakMatrix/gvisor (1.00s)\n"
        "    --- PASS: TestPoolDisconnectMidRun/gvisor (1.00s)\nPASS\nok  \tvora\t1.0s\n"
    )
    os.utime(report, (0, 0))

    assert cli.main(["bench-summary", str(bencher.raw), "--leak-vora", f"gvisor={report}"]) == 0

    printed = capsys.readouterr().out
    assert "| gvisor | stale: older than the session started " in printed
    assert "| gvisor | passed |" not in printed


def test_denied_syscalls_and_blocked_network_never_read_as_zero(bencher: Bench) -> None:
    assert bencher.run("warm") == 0

    text = render_summary(load_raw(bencher.raw))

    assert "- Denied syscalls: not measured." in text
    assert "- Blocked network attempts: not measured: network mode none" in text
    assert "denied" not in json.dumps(bencher.rows("run")[0])


@pytest.mark.parametrize(
    ("values", "p50", "p90", "p99", "maximum"),
    [
        ([1.0], 1.0, 1.0, 1.0, 1.0),
        ([3.0, 1.0, 2.0, 4.0], 2.0, 4.0, 4.0, 4.0),
        ([float(n) for n in range(1, 101)], 50.0, 90.0, 99.0, 100.0),
    ],
)
def test_percentiles_are_nearest_rank(values: list[float], p50: float, p90: float, p99: float, maximum: float) -> None:
    result = percentiles(values)
    assert (result.count, result.p50, result.p90, result.p99, result.max) == (len(values), p50, p90, p99, maximum)


def test_a_percentile_ignores_what_was_not_reported_and_counts_it() -> None:
    result = percentiles([None, 10.0, None, 20.0])
    assert (result.count, result.missing, result.p50, result.max) == (2, 2, 10.0, 20.0)
    assert percentiles([None]).p50 is None
    assert percentiles([]).count == 0
