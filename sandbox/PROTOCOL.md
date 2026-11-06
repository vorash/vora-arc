# Runner protocol

`runner.py` runs inside the sandbox. The client starts it with one exec and
talks to it only through stdin and stdout.

## stdin

One JSON object:

```json
{
  "program": "def transform(grid): ...",
  "inputs": [{"index": 0, "is_test": false, "grid": [[0, 1], [1, 0]]}],
  "per_input_timeout_ms": 2000
}
```

Inputs are train inputs first (index 0 to n-1), then test inputs.

## stdout

Newline-delimited JSON. The runner writes nothing else to stdout.

One result line per input, written as soon as that input finishes, in input
order:

```json
{"index": 0, "status": "OK", "output": [[1, 0], [0, 1]], "error": null, "wall_ms": 3}
```

- `status` is `OK`, `ERROR`, `TIMEOUT` or `INVALID`.
- `output` is set only when `status` is `OK`: a rectangular list of lists of
  ints 0-9, 1x1 to 30x30.
- `error` is a traceback or reason, truncated to 2 KB.

Then one final line:

```json
{"done": true, "stderr_tail": "..."}
```

`stderr_tail` is the last 4 KB of everything the program wrote to stdout or
stderr.

The runner streams lines so a client keeps every finished result when Vora kills
the whole batch (timeout, OOM). A batch with no final line was killed.
Inputs with no result line take their status from the kill reason.
