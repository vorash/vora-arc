# How to run experiment 1

Experiment 1 compares three ways of running one program: a fresh sandbox per run, a warm pool
with a reset, and a warm pool with no reset. No results exist yet. This page gives the commands
and says what limits each number.

| Arm (`--mode`) | Pool shape | What it measures |
|---|---|---|
| `cold` | `size` 0, `max_size` = concurrency | A new sandbox for every run |
| `warm` | `size` = `max_size` = concurrency, `max_runs` 100 | A pre-started member, reset between runs |
| `warm-no-reset` | The same, with `reuse` `unsafe_no_reset` | The same with no reset. A control, never a way to run programs |

The arms run the same program on the same task inputs at the same concurrency.

## Before you start

You need:

- A Vora server with pools, on a host that has spare capacity for `max_size` sandboxes per arm.
- The image: run `sandbox/build.sh` on the host.
- The data: run `scripts/download_data.sh`.

| Variable | For | Needed |
|---|---|---|
| `VORA_API_URL`, `VORA_API_KEY` | The tenant's key, which makes every run | Always |
| `VORA_ADMIN_API_KEY` | An admin key, which declares the no-reset pool. A global admin's key also lets `bench` read the server version | For `warm-no-reset` |
| `VORA_ARC_TENANT_ID` | The tenant the no-reset pool belongs to, which must be the tenant of `VORA_API_KEY` | With a global admin's key |
| `VORA_ARC_PROFILE` | The profile, unless you pass `--profile` | No |

If `VORA_API_KEY` is bound to an agent, the API answers 404 for a no-reset pool declared without
that agent. Use a tenant key with no agent.

## Open the no-reset gate

The `warm-no-reset` arm leaves one run's files and processes for the next, so it takes two
separate permissions. The runner must allow it, and an admin must declare it.

1. Set `VORA_POOL_UNSAFE_REUSE=allow` in the runner's environment.
2. Restart the runner.
3. After the experiment, remove the variable and restart the runner again.

Without the variable, the declare fails and `bench` exits with the API's message. `solve` can't
declare this shape.

## Check the host

These checks need the host, because the API doesn't report them.

1. Check that nothing else is running.

   ```sh
   uptime
   nproc
   ```

2. Check that the runner resolves the image through containerd. In `auto` mode the runner retries
   containerd on every start of an image that only the local cache has
   ([vorash/vora#148](https://github.com/vorash/vora/issues/148), open), which would inflate the
   `cold` arm. The API can't show this: the `image_rootfs` field exists, and nothing fills it.

   ```sh
   ctr --address "$XDG_RUNTIME_DIR/containerd/containerd.sock" --namespace vora images ls | grep vora/arc
   ```

   If the image is listed, pass `--image-resolved-via containerd`. If it isn't, run
   `sandbox/build.sh` and check again. Without the flag, `bench` records the source as unconfirmed
   and says so in every summary.

3. Read the server version. `bench` reads it from `GET /v1/runners` when `VORA_ADMIN_API_KEY` is a
   global admin's key. Otherwise, read it here and pass it with `--server-version`. The address is
   the runner's `VORA_METRICS_ADDR`.

   ```sh
   curl -s http://127.0.0.1:9101/metrics | grep vora_build_info
   ```

Run `bench` on the host if you can. `bench` reads load and CPU count on the machine it runs on, and
an SSH tunnel adds its own limit to every number. If you use a tunnel, take `uptime` on the host
yourself, and don't compare those numbers with an on-host run.

## Prove the wiring

Run each arm once at a small size, and read the output before you trust a long run.

```sh
uv run vora-arc bench --mode warm --profile profiles/python-arc-bwrap.toml \
  --candidates 50 --raw results/bench/smoke.jsonl
```

Expect `50 ok, 0 failed` and `not what this arm requires: 0`. The command exits 1 if any measured
run failed or wasn't in the arm's shape.

## Run the arms in turn

Alternate the arms, so that drift on the host affects all three. Use one raw file per backend,
because a summary compares every session in its file. This loop makes 10,000 measured runs per arm:

```sh
RAW=results/bench/experiment-1-bwrap.jsonl
for round in 1 2 3 4 5; do
  for mode in cold warm warm-no-reset; do
    uv run vora-arc bench --mode "$mode" --profile profiles/python-arc-bwrap.toml \
      --candidates 2000 --concurrency 8 --image-resolved-via containerd --raw "$RAW"
  done
done
```

To change the program or the task, pass `--program` and `--task`. The defaults are
`solutions/3c9b0459.py` and task `3c9b0459`. `--warmup` defaults to three times `--concurrency`.

Each session appends to the raw file: a header, one line per run, and a footer. Each arm deletes its
pool at the end. A killed `bench` leaves its pool holding capacity. Delete it with
`curl -X DELETE "$VORA_API_URL/v1/pools/<name>" -H "Authorization: Bearer $VORA_API_KEY"`, with
the name from the first lines of output.

## Rebuild the summary

```sh
uv run vora-arc bench-summary results/bench/experiment-1-bwrap.jsonl
```

The summary reads only the raw file. It gives p50, p90, p99, max and count for each time, as
nearest-rank percentiles over the runs that passed, and a table of each arm's median and range
across sessions. Failed runs are counted beside the times, by cause. Runs that weren't in the arm's
shape are counted and stay in the times, because they are part of what that arm costs.

## What limits each arm's number

`wall_ms` runs from sending the request to reading the `exit` frame, on the client's clock.
`cycle_ms` goes on to the end of the stream, so it includes the reset. Latency comes from `wall_ms`
and programs per second reflects `cycle_ms`, so read both.

**`cold`.** A sandbox start dominates. `startup_ms` is the borrow wait plus the start. With `max_size`
equal to the concurrency, a retired member keeps its slot until its destroy returns, so a run can
wait for the previous run's destroy and that wait shows in its startup. A cold member also skips
work the other arms do at start: `reused()` is false, so it captures no reset manifest and doesn't
deny SysV and POSIX IPC. The arms are therefore not identical beyond pool shape. If the image isn't
in containerd, every start also carries a registry attempt (#148).

**`warm`.** The program's own run dominates `wall_ms`: the runner starts a Python interpreter for each
run. The reset falls outside `wall_ms`, but the client holds its slot until `run_done`, so the reset
lowers programs per second. On gVisor a reset starts `runsc` three times. A member retires after
100 runs, or at the default `max_age` of 30 minutes, and a replacement starts in the background. A
borrower then waits, and the wait shows in `startup_ms`. It still counts as warm. Every arm sets
`borrow_timeout_ms` to 60 seconds, so a slow replacement shows as a slow run. A longer wait is a
refusal, and that is a failed run.

**`warm-no-reset`.** It runs what `warm` runs, minus the reset, so the gap to `warm` is the reset's cost
and nothing more. The speed comes from leaving one run's files and processes for the next, which is
why the reset exists. `test_without_a_reset_the_same_write_does_survive` shows the leak. Every output
of this arm says `UNSAFE`. Don't quote its number as something a pool can deliver safely.

**All arms.**

- The client can be the limiter. It is one Python process parsing every chunk. Compare `client CPU`
  with the measured time in the footer. If they are close, you measured the client.
- Each sandbox has one CPU, so concurrency above the host's core count measures contention.
- Check the arithmetic: programs per second can't exceed the concurrency times 1000 divided by the
  mean `cycle_ms`. A figure above that measured something else.
- `bench` doesn't find what limits a run. Profile the host in a separate run, and don't report that run.

## How `bench` answers the benchmark checklist

| Question | What `bench` does | What is left to you |
|---|---|---|
| Did it error? | Counts every refusal, broken stream and bad exit, by cause. Retries nothing | Read the counts |
| Did it even happen? | Runs `verify` on each result, so a run counts only if the program gave the right train outputs. Records a digest of the outputs, and the summary shows how many distinct ones it saw | Expect 1 distinct output |
| Does it reproduce? | Shows each arm's median and range across sessions, and says when there are fewer than 5 | Run the loop above. A gap inside the range is no measurable difference |
| Was it tuned? | Uses the profile's limits on every arm. `borrow_timeout_ms` is 60 s, where `solve --pool` keeps Vora's default of 2 s | Use a host like the one you care about |
| Why not double? | Records load, CPU count and client CPU | Find the limiter with a profiler |

`bench` measures with its own clock and doesn't read `runs_total`, because that counter counts a run
whose client left before its exec ([vorash/vora#149](https://github.com/vorash/vora/issues/149)).

The spec's experiment uses a mix of solutions, mutated variants and junk. `bench` runs one program,
because a mix would make the arms differ by which program each run drew.
