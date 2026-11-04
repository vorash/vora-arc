"""runner.py run as a subprocess on the host, with benign programs only.

Hostile programs (fork bombs, huge allocations, network) run only in a real
Vora sandbox; see the sandbox-marked tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "sandbox" / "runner.py"
TIMEOUT_MS = 300
GRIDS = [[[0, 1], [2, 3]], [[4]], [[5, 6, 7]]]


def request(program: str, grids: list[Any], timeout_ms: int = TIMEOUT_MS) -> bytes:
    inputs = [{"index": i, "is_test": i == len(grids) - 1, "grid": g} for i, g in enumerate(grids)]
    body = {"program": textwrap.dedent(program), "inputs": inputs, "per_input_timeout_ms": timeout_ms}
    return json.dumps(body).encode()


def run(program: str, grids: list[Any] = GRIDS, timeout_ms: int = TIMEOUT_MS) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    proc = subprocess.run(
        [sys.executable, str(RUNNER)],
        input=request(program, grids, timeout_ms),
        capture_output=True,
        timeout=30,
        check=True,
    )
    # Every stdout line must be protocol JSON: program output never leaks in.
    lines = [json.loads(line) for line in proc.stdout.decode().splitlines()]
    *results, done = lines
    assert done.keys() == {"done", "stderr_tail"} and done["done"] is True
    assert [r["index"] for r in results] == list(range(len(grids))), "one result per input, in input order"
    for r in results:
        assert r.keys() == {"index", "status", "output", "error", "wall_ms"}
        assert (r["output"] is not None) == (r["status"] == "OK")
        assert isinstance(r["wall_ms"], int) and r["wall_ms"] >= 0
    return results, done


def statuses(results: list[dict[str, Any]]) -> list[str]:
    return [r["status"] for r in results]


MIRROR = """
    def transform(grid):
        return [row[::-1] for row in grid]
"""


def test_correct_transform_returns_every_output() -> None:
    results, _ = run(MIRROR)
    assert statuses(results) == ["OK", "OK", "OK"]
    assert [r["output"] for r in results] == [[[1, 0], [3, 2]], [[4]], [[7, 6, 5]]]
    assert all(r["error"] is None for r in results)


def test_missing_transform_errors_every_input_with_a_clear_message() -> None:
    results, _ = run("def solve(grid):\n    return grid\n")
    assert statuses(results) == ["ERROR"] * 3
    assert all("does not define a callable transform" in r["error"] for r in results)


def test_syntax_error_errors_every_input() -> None:
    results, _ = run("def transform(grid)\n    return grid\n")
    assert statuses(results) == ["ERROR"] * 3
    assert all("SyntaxError" in r["error"] for r in results)


def test_program_raising_while_loading_errors_every_input() -> None:
    results, _ = run("raise RuntimeError('broken at import')\n")
    assert statuses(results) == ["ERROR"] * 3
    assert all("broken at import" in r["error"] for r in results)


def test_one_input_raising_keeps_the_others() -> None:
    results, _ = run(
        """
        def transform(grid):
            if grid == [[4]]:
                raise ValueError("cannot handle 4")
            return grid
        """
    )
    assert statuses(results) == ["OK", "ERROR", "OK"]
    assert "ValueError: cannot handle 4" in results[1]["error"]
    assert "runner.py" not in results[1]["error"], "traceback starts in program code"


def test_sys_exit_inside_transform_is_an_error_for_that_input_only() -> None:
    results, _ = run(
        """
        import sys
        def transform(grid):
            if grid == [[4]]:
                sys.exit(1)
            return grid
        """
    )
    assert statuses(results) == ["OK", "ERROR", "OK"]
    assert "SystemExit" in results[1]["error"]


def test_worker_dying_mid_batch_keeps_the_others() -> None:
    results, _ = run(
        """
        import os
        def transform(grid):
            if grid == [[4]]:
                os._exit(3)
            return grid
        """
    )
    assert statuses(results) == ["OK", "ERROR", "OK"]
    assert "exited with code 3" in results[1]["error"]


def test_garbage_on_the_result_pipe_errors_that_input_only() -> None:
    # The program shares a process with the result pipe, so the parent must
    # survive anything written to it, here JSON nested past the parser's limit.
    results, _ = run(
        """
        import os
        def transform(grid):
            if grid == [[4]]:
                for fd in range(3, 64):
                    try:
                        os.write(fd, b"[" * 100_000 + b"\\n")
                    except OSError:
                        pass
            return grid
        """
    )
    assert statuses(results) == ["OK", "ERROR", "OK"]
    assert "malformed" in results[1]["error"]


def test_worker_killed_by_a_realtime_signal_keeps_the_others() -> None:
    results, _ = run(
        """
        import os, signal
        def transform(grid):
            if grid == [[4]]:
                os.kill(os.getpid(), signal.SIGRTMIN + 1)
            return grid
        """
    )
    assert statuses(results) == ["OK", "ERROR", "OK"]
    assert "killed by" in results[1]["error"]


def test_worker_that_leaves_its_process_group_is_still_cut_off() -> None:
    results, _ = run(
        """
        import os
        def transform(grid):
            if grid == [[4]]:
                os.setpgid(0, os.getpgid(os.getppid()))
                while True:
                    pass
            return grid
        """
    )
    assert statuses(results) == ["OK", "TIMEOUT", "OK"]


@pytest.mark.parametrize(
    ("expr", "reason"),
    [
        pytest.param("None", "NoneType", id="None"),
        pytest.param("[[1, 2], [3]]", "row 1 has 1 cells but row 0 has 2", id="ragged"),
        pytest.param("[[1, 11]]", "cell [0][1] is 11", id="value 11"),
        pytest.param("[[-1]]", "cell [0][0] is -1", id="negative"),
        pytest.param("[[True]]", "bool", id="bool"),
        pytest.param("[[1.0]]", "float", id="float"),
        pytest.param("[(1, 2)]", "row 0 is tuple", id="tuple row"),
        pytest.param("[]", "no rows", id="empty"),
        pytest.param("[[]]", "row 0 has no cells", id="empty row"),
        pytest.param("[[0]] * 31", "more than 30 rows", id="31 rows"),
        pytest.param("[[0] * 31]", "more than 30 cells", id="31 columns"),
        pytest.param("[[0] * 31 for _ in range(31)]", "more than 30", id="31x31"),
        pytest.param("[[10**100]]", "large int", id="huge int"),
    ],
)
def test_invalid_outputs_are_rejected_with_a_reason(expr: str, reason: str) -> None:
    results, _ = run(f"def transform(grid):\n    return {expr}\n", grids=[[[0]]])
    assert statuses(results) == ["INVALID"]
    assert reason in results[0]["error"]


def test_30x30_is_the_largest_valid_output() -> None:
    results, _ = run("def transform(grid):\n    return [[9] * 30 for _ in range(30)]\n", grids=[[[0]]])
    assert statuses(results) == ["OK"]


def test_busy_loop_times_out_and_the_rest_still_report() -> None:
    results, _ = run(
        """
        def transform(grid):
            if grid == [[4]]:
                while True:
                    pass
            return grid
        """
    )
    assert statuses(results) == ["OK", "TIMEOUT", "OK"]
    assert results[2]["output"] == [[5, 6, 7]], "a fresh worker ran the input after the timeout"
    assert results[1]["wall_ms"] >= TIMEOUT_MS


def test_program_that_swallows_signals_is_still_cut_off() -> None:
    # Catches BaseException around a busy loop, ignores SIGALRM and SIGTERM,
    # and spins in C code that never returns to the interpreter, as numpy can.
    results, _ = run(
        """
        import collections, itertools, signal
        for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, signal.SIG_IGN)
        def transform(grid):
            if grid == [[4]]:
                while True:
                    try:
                        collections.deque(itertools.count(), maxlen=0)
                    except BaseException:
                        pass
            return grid
        """
    )
    assert statuses(results) == ["OK", "TIMEOUT", "OK"]


def test_hang_while_loading_costs_one_timeout_not_one_per_input() -> None:
    started = time.monotonic()
    results, _ = run("while True:\n    pass\n", grids=[[[0]]] * 5)
    elapsed = time.monotonic() - started
    assert statuses(results) == ["TIMEOUT"] * 5
    assert "loading" in results[0]["error"]
    assert elapsed < 5 * TIMEOUT_MS / 1000


def test_large_print_is_drained_and_only_the_tail_kept() -> None:
    results, done = run(
        """
        import sys
        def transform(grid):
            for _ in range(5000):
                print("x" * 1000)
            sys.stderr.write("end-of-output\\n")
            return grid
        """,
        grids=[[[1]]],
        timeout_ms=10_000,
    )
    assert statuses(results) == ["OK"]
    tail = done["stderr_tail"]
    assert tail.endswith("end-of-output\n")
    assert len(tail.encode()) <= 4096


def test_long_error_is_truncated_to_2kb() -> None:
    results, _ = run("def transform(grid):\n    raise ValueError('e' * 100_000)\n", grids=[[[1]]])
    assert statuses(results) == ["ERROR"]
    assert len(results[0]["error"].encode()) <= 2048


def test_result_lines_stream_before_the_batch_finishes() -> None:
    # A client keeps finished results when Vora kills the whole batch, so the
    # first result must be on stdout while a later input is still running.
    program = """
        def transform(grid):
            if grid == [[4]]:
                while True:
                    pass
            return grid
    """
    proc = subprocess.Popen(
        [sys.executable, str(RUNNER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdin and proc.stdout
    proc.stdin.write(request(program, [[[1]], [[4]]], timeout_ms=1000))
    proc.stdin.close()
    first = json.loads(proc.stdout.readline())
    assert first["index"] == 0 and first["status"] == "OK"
    assert proc.poll() is None, "runner is still working on input 1"
    rest = [json.loads(line) for line in proc.stdout]
    assert proc.wait(timeout=30) == 0
    assert rest[0]["status"] == "TIMEOUT" and rest[1]["done"] is True


def test_bad_request_exits_nonzero_without_protocol_output() -> None:
    proc = subprocess.run([sys.executable, str(RUNNER)], input=b"not json", capture_output=True, timeout=30)
    assert proc.returncode == 2
    assert proc.stdout == b""
    assert b"bad request" in proc.stderr
