"""Run one ARC program against a batch of grids. See PROTOCOL.md.

The parent process never runs program code. It forks a worker that execs the
program once and calls transform on each input in turn, sending each result
back over a private pipe. The parent enforces the per-input timeout from
outside with SIGKILL, validates every output, and streams result lines.
"""

from __future__ import annotations

import copy
import io
import json
import os
import select
import signal
import sys
import time
import traceback
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

MAX_SIDE = 30
ERROR_LIMIT = 2048
TAIL_LIMIT = 4096
MESSAGE_LIMIT = 256 * 1024
FINAL_DRAIN_LIMIT = 1 << 20
LARGE_INT = 10**9

# Vora builds a sandbox's environment from the exec request, not from the
# image config, so the image's ENV lines never reach this process. numpy's
# BLAS would otherwise start one thread per host CPU, and threads count
# against the sandbox's 16-process limit.
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


@dataclass(frozen=True)
class Input:
    index: int
    grid: list[Any]


@dataclass(frozen=True)
class Request:
    program: str
    inputs: tuple[Input, ...]
    timeout_ms: int

    @property
    def timeout_s(self) -> float:
        return self.timeout_ms / 1000


class BadRequest(Exception):
    pass


class InvalidOutput(Exception):
    pass


def parse_request(raw: bytes) -> Request:
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise BadRequest(f"stdin is not JSON: {e}") from None
    if not isinstance(data, dict):
        raise BadRequest("stdin must be a JSON object")
    program = data.get("program")
    timeout_ms = data.get("per_input_timeout_ms")
    raw_inputs = data.get("inputs")
    if not isinstance(program, str):
        raise BadRequest("program must be a string")
    if type(timeout_ms) is not int or timeout_ms <= 0:
        raise BadRequest("per_input_timeout_ms must be a positive integer")
    if not isinstance(raw_inputs, list):
        raise BadRequest("inputs must be a list")
    inputs = []
    for item in raw_inputs:
        if not (isinstance(item, dict) and type(item.get("index")) is int and isinstance(item.get("grid"), list)):
            raise BadRequest("each input needs an integer index and a grid list")
        inputs.append(Input(index=item["index"], grid=item["grid"]))
    return Request(program=program, inputs=tuple(inputs), timeout_ms=timeout_ms)


def truncate(text: str, limit: int = ERROR_LIMIT) -> str:
    data = text.encode("utf-8", "replace")
    if len(data) <= limit:
        return text
    return "..." + data[-(limit - 3) :].decode("utf-8", "ignore")


def describe(value: object) -> str:
    if isinstance(value, dict) and isinstance(value.get("type"), str):
        return str(value["type"])
    if isinstance(value, bool):
        return f"{value} (a bool)"
    if isinstance(value, int):
        return str(value)
    return type(value).__name__


def parse_grid(value: object) -> list[list[int]]:
    """Validate an output the worker sent. The worker is untrusted."""
    if not isinstance(value, list):
        raise InvalidOutput(f"output is {describe(value)}, expected a list of lists")
    if not value:
        raise InvalidOutput("output has no rows")
    if len(value) > MAX_SIDE:
        raise InvalidOutput(f"output has more than {MAX_SIDE} rows")
    width = None
    for r, row in enumerate(value):
        if not isinstance(row, list):
            raise InvalidOutput(f"row {r} is {describe(row)}, expected a list")
        if not row:
            raise InvalidOutput(f"row {r} has no cells")
        if len(row) > MAX_SIDE:
            raise InvalidOutput(f"row {r} has more than {MAX_SIDE} cells")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise InvalidOutput(f"row {r} has {len(row)} cells but row 0 has {width}")
        for c, cell in enumerate(row):
            if type(cell) is not int or not 0 <= cell <= 9:
                raise InvalidOutput(f"cell [{r}][{c}] is {describe(cell)}, expected an int from 0 to 9")
    return value


def exit_description(status: int) -> str:
    code = os.waitstatus_to_exitcode(status)
    if code < 0:
        try:
            name = signal.Signals(-code).name
        except ValueError:
            name = f"signal {-code}"
        return f"worker was killed by {name}"
    return f"worker exited with code {code}"


class Capture:
    """The program's stdout and stderr: one pipe, drained continuously, last 4 KB kept."""

    def __init__(self) -> None:
        self.read_fd, self.write_fd = os.pipe()
        os.set_blocking(self.read_fd, False)
        self._tail = bytearray()

    def read_once(self) -> int:
        try:
            chunk = os.read(self.read_fd, 65536)
        except BlockingIOError:
            return 0
        self._tail += chunk
        del self._tail[:-TAIL_LIMIT]
        return len(chunk)

    def finish(self) -> str:
        os.close(self.write_fd)
        # A process the program detached from the worker could keep writing
        # forever, so stop after a bound instead of waiting for EOF.
        total = 0
        while total < FINAL_DRAIN_LIMIT:
            n = self.read_once()
            if n == 0:
                break
            total += n
        os.close(self.read_fd)
        return self._tail.decode("utf-8", "replace")


class Worker:
    """One forked child running the program over a run of inputs."""

    def __init__(self, program: str, inputs: tuple[Input, ...], capture: Capture) -> None:
        result_r, result_w = os.pipe()
        sys.stdout.flush()
        sys.stderr.flush()
        pid = os.fork()
        if pid == 0:
            code = 70
            try:
                os.close(result_r)
                os.close(capture.read_fd)
                worker_main(program, inputs, result_w, capture.write_fd)
                code = 0
            finally:
                os._exit(code)
        os.close(result_w)
        try:
            os.setpgid(pid, pid)
        except OSError:
            pass
        self.pid = pid
        self.result_fd = result_r
        self.capture = capture
        self.buffer = bytearray()
        self.status: int | None = None
        self.failure = ""

    def receive(self, deadline: float) -> dict[str, Any] | None:
        """Next message from the worker; None if it died or broke the protocol.

        Raises TimeoutError at the deadline.
        """
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self.buffer[:newline])
                del self.buffer[: newline + 1]
                try:
                    message = json.loads(line)
                except (ValueError, RecursionError):
                    message = None
                if isinstance(message, dict):
                    return message
                self.failure = "worker sent a malformed message"
                return None
            if len(self.buffer) > MESSAGE_LIMIT:
                self.failure = f"worker sent a message over {MESSAGE_LIMIT} bytes"
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            ready, _, _ = select.select([self.result_fd, self.capture.read_fd], [], [], remaining)
            if self.capture.read_fd in ready:
                self.capture.read_once()
            if self.result_fd in ready:
                chunk = os.read(self.result_fd, 65536)
                if not chunk:
                    self.failure = self._exit_reason()
                    return None
                self.buffer += chunk

    def _exit_reason(self) -> str:
        for _ in range(40):
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.status = status
                return exit_description(status)
            time.sleep(0.005)
        return "worker closed its result channel"

    def kill(self) -> None:
        # The group takes any children the program started; the worker itself
        # is killed by pid too because it can move to another group.
        targets = [(os.killpg, self.pid)]
        if self.status is None:
            targets.append((os.kill, self.pid))
        for send_kill, target in targets:
            try:
                send_kill(target, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self.status is None:
            os.waitpid(self.pid, 0)
        os.close(self.result_fd)


def result_line(index: int, status: str, wall_ms: int, output: list[list[int]] | None = None, error: str | None = None) -> dict[str, Any]:
    return {"index": index, "status": status, "output": output, "error": error, "wall_ms": wall_ms}


def elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


def run_worker(request: Request, inputs: tuple[Input, ...], capture: Capture) -> Iterator[dict[str, Any]]:
    """Yield results for a prefix of inputs, stopping after the first that ends the worker."""
    timeout_ms = request.timeout_ms
    worker = Worker(request.program, inputs, capture)
    try:
        try:
            message = worker.receive(time.monotonic() + request.timeout_s)
        except TimeoutError:
            reason = f"program did not finish loading within {timeout_ms} ms"
            for item in inputs:
                yield result_line(item.index, "TIMEOUT", 0, error=reason)
            return
        if message != {"loaded": True}:
            if message is not None and isinstance(message.get("load_error"), str):
                reason = truncate(message["load_error"])
            else:
                reason = f"{worker.failure or 'worker broke the protocol'} while loading the program"
            for item in inputs:
                yield result_line(item.index, "ERROR", 0, error=reason)
            return
        for item in inputs:
            started = time.monotonic()
            try:
                message = worker.receive(started + request.timeout_s)
            except TimeoutError:
                yield result_line(item.index, "TIMEOUT", elapsed_ms(started), error=f"transform did not return within {timeout_ms} ms")
                return
            wall_ms = elapsed_ms(started)
            if message is not None and "output" in message:
                try:
                    grid = parse_grid(message["output"])
                except InvalidOutput as e:
                    yield result_line(item.index, "INVALID", wall_ms, error=truncate(str(e)))
                else:
                    yield result_line(item.index, "OK", wall_ms, output=grid)
            elif message is not None and isinstance(message.get("error"), str):
                yield result_line(item.index, "ERROR", wall_ms, error=truncate(message["error"]))
            else:
                yield result_line(item.index, "ERROR", wall_ms, error=worker.failure or "worker sent an unknown message")
                return
    finally:
        worker.kill()


def run_batch(request: Request) -> None:
    capture = Capture()
    done = 0
    while done < len(request.inputs):
        for line in run_worker(request, request.inputs[done:], capture):
            emit(line)
            done += 1
    emit({"done": True, "stderr_tail": capture.finish()})


def emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


# Worker side. Everything below runs in the forked child alongside program
# code, so the parent trusts none of what it sends.


def encode(value: object) -> object:
    """A JSON form of a transform result that keeps the types the parent checks.

    Anything that is not an exact list or int becomes a {"type": name} marker,
    and lists are cut at MAX_SIDE + 1 so a huge result stays a small message.
    """
    value = from_numpy(value)
    if type(value) not in (list, tuple):
        return {"type": type(value).__name__}
    return [encode_row(row) for row in value[: MAX_SIDE + 1]]  # type: ignore[index]


def encode_row(row: object) -> object:
    row = from_numpy(row)
    if type(row) not in (list, tuple):
        return {"type": type(row).__name__}
    return [encode_cell(cell) for cell in row[: MAX_SIDE + 1]]  # type: ignore[index]


def encode_cell(cell: object) -> object:
    cell = from_numpy(cell)
    if type(cell) is bool:
        return cell
    if type(cell) is int:
        return cell if -LARGE_INT < cell < LARGE_INT else {"type": "large int"}
    return {"type": type(cell).__name__}


def from_numpy(value: object) -> object:
    # Model-written programs routinely return arrays or numpy ints. Converting
    # them here keeps those answers; the parent still validates the result.
    kind = type(value)
    if kind.__module__ != "numpy":
        return value
    if kind.__name__ == "ndarray":
        return value.tolist()  # type: ignore[attr-defined]
    if kind.__name__.startswith(("int", "uint")):
        return int(value)  # type: ignore[call-overload]
    return value


def format_error(e: BaseException) -> str:
    # Drop the worker's own frame so the traceback starts in program code.
    tb = e.__traceback__.tb_next if e.__traceback__ else None
    return truncate("".join(traceback.format_exception(type(e), e, tb)))


def worker_main(program: str, inputs: tuple[Input, ...], result_fd: int, capture_fd: int) -> None:
    os.setpgid(0, 0)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.close(devnull)
    os.dup2(capture_fd, 1)
    os.dup2(capture_fd, 2)
    os.close(capture_fd)
    # stderr is already line-buffered; match it so the tail keeps write order.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)

    # The program may rebind any of these; keep our own references.
    write, dumps, deepcopy = os.write, json.dumps, copy.deepcopy
    stdout, stderr = sys.stdout, sys.stderr

    def send(message: dict[str, object]) -> None:
        # The parent SIGKILLs the worker when it is done, so flush now or the
        # program's buffered prints are lost.
        for stream in (stdout, stderr):
            try:
                stream.flush()
            except BaseException:
                pass
        data = (dumps(message) + "\n").encode()
        while data:
            data = data[write(result_fd, data) :]

    namespace: dict[str, Any] = {"__name__": "__program__"}
    try:
        code = compile(program, "<program>", "exec")
    except BaseException as e:
        send({"load_error": truncate("".join(traceback.format_exception_only(type(e), e)))})
        return
    try:
        exec(code, namespace)
    except BaseException as e:
        send({"load_error": format_error(e)})
        return
    transform = namespace.get("transform")
    if not callable(transform):
        send({"load_error": "program does not define a callable transform(grid)"})
        return
    send({"loaded": True})
    message: dict[str, object]
    for item in inputs:
        try:
            message = {"output": encode(transform(deepcopy(item.grid)))}
        except BaseException as e:
            try:
                message = {"error": format_error(e)}
            except BaseException:
                message = {"error": "transform raised an exception that could not be formatted"}
        send(message)


def main() -> int:
    try:
        request = parse_request(sys.stdin.buffer.read())
    except BadRequest as e:
        print(f"runner: bad request: {e}", file=sys.stderr)
        return 2
    os.environ.update(THREAD_ENV)
    run_batch(request)
    return 0


if __name__ == "__main__":
    sys.exit(main())
