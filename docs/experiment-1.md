# How to run experiment 1

Experiment 1 measures the cost of isolation. It runs a corpus of synthetic candidates (hand-written
solutions, mutated variants and junk) three ways, and reports programs per second, p50, p99 and the
leak-test results. No results exist yet. This page gives the commands and says what limits each
number.

| Arm (`--mode`) | Pool shape | What it measures |
|---|---|---|
| `cold` | `size` 0, `max_size` = 2 x concurrency | A new sandbox for every run |
| `warm` | `size` = `max_size` = concurrency, `max_runs` 100 | A pre-started member, reset between runs |
| `warm-no-reset` | The same, with `reuse` `unsafe_no_reset` | The same with no reset. A control, never a way to run programs |

The arms run the same candidates in the same order at the same concurrency. The client never runs
more than `--concurrency` programs at a time on any arm.

## The corpus

`bench` builds the corpus from `--seed`, `--candidates` and `solutions/`. The same inputs give the
same candidates in the same order, so all three arms run exactly the same programs. The raw header
records the seed, the mix, the counts, the number of distinct programs and a hash. Each run records
its candidate's index, class, task and `program_sha256`.

| Class | Share | What it is | What it exercises | Verdict from a healthy arm |
|---|---|---|---|---|
| `hand_written` | 10.00% | The 10 programs in `solutions/`, repeated | A whole run, and a check that the arm works | `passed` |
| `mutated` | 50.10% | A solution with 1 to 3 mechanical changes: a flipped operator, a changed constant, swapped indexes or operands, a swapped builtin | A whole run of a plausible near-miss | Mostly `failed`, some `crashed` or `invalid`, and a mutation can leave the answer right |
| `syntax_error` | 10.00% | A solution with a syntax error | The runner, ending when the program loads | `crashed` |
| `missing_transform` | 5.00% | A solution with `transform` renamed or not callable | The same, after the program loads | `crashed` |
| `wrong_shape` | 12.00% | A solution that returns a row, nothing, a string, a ragged grid, too large a grid, cells out of range, or too few rows | A whole run, then output validation | `invalid` or `failed` |
| `crash` | 12.00% | A solution that raises when called or indexes out of range | The runner handling an exception per input | `crashed` |
| `slow` | 0.50% | A solution that busy-waits 0.1 to 0.2 s per input | CPU held for a bounded time | `passed` |
| `memory_hungry` | 0.30% | A solution that touches 64 to 96 MiB per input | Pages used, then freed | `passed` |
| `timeout` | 0.10% | A solution followed by a loop that never ends | One per-input timeout, then the runner gives up | `timeout` |

**Why this mix.** The mix moves every number, so compare arms only on one corpus. A fast failure
spends almost nothing in the program, which leaves startup and reset to dominate. A slow program does
the opposite. The experiment asks what isolation costs a program that really runs, so 84.9% of this
corpus (everything but `syntax_error`, `missing_transform` and `timeout`) calls `transform` on every
input. The other 15.1% stops while loading, because generated programs can do that and the arms must
handle it too. The mix is a choice for this experiment. It doesn't describe any model's output.

**Why so little of the expensive classes.** `slow`, `memory_hungry` and `timeout` together are 0.9%, so
they don't dominate the throughput. That doesn't make the overall p99 typical. They fill most of the
slowest 1%: with 18 of them in 2,000 candidates, and all 18 slower than any ordinary program, the
overall p99 is the 3rd slowest of the 1,982 ordinary runs. So the summary leads with an **ordinary
programs** row that leaves those three classes out. They show in the all-classes row, in their own rows
and in the share of slot time.

**How little a session's p99 rests on.** A nearest-rank p99 over one session of 2,000 rests on about 20
runs, so one or two slow runs move it. The summary shows a p99 pooled across the complete sessions of an
arm next to the range of each session's own p99. Read both.

**Why a timeout doesn't dominate.** A loop in `transform` costs one per-input timeout per input, and
enough inputs reach the 10 s batch limit, where Vora kills the run. This corpus has no program that
reaches that limit. The `timeout` class hangs while loading, so the runner reports every input as
timed out after one per-input timeout. This arithmetic comes from the profiles and the mix, and isn't
a measurement: 10,000 candidates hold 10 timeouts at 2 s each, and 50 slow programs at no more than
0.2 s per input on no more than 6 inputs. Those two classes hold at most 80 s of slot time, the same
on every arm, or at most 80 / concurrency seconds of wall time. `memory_hungry` isn't in that sum.

**What isn't here.** Programs that kill their sandbox, reach the memory limit or touch the host are
in `tests/hostile/`, and the hostile suite covers them. A kill can cost a member, so it would change
the arm's shape instead of measuring it. Nothing in this corpus plants state for a later run, so
matching verdicts on the no-reset arm say nothing about safety. The leak tests answer that.

## Before you start

You need:

- A Vora server with pools, on a host that has spare capacity for `max_size` sandboxes per arm. Vora
  reserves CPU and memory for all of `max_size` when a pool is declared, so the `cold` arm needs room
  for twice the concurrency. If the runner hasn't got it, the declare is refused and `bench` exits
  with the API's message. Lower `--concurrency` on every arm.
- For `warm` and `warm-no-reset` on gVisor, the Vora release that contains
  [vorash/vora#150](https://github.com/vorash/vora/pull/150), which is open, so no release has it yet.
  Without it the declare is refused with `backend cannot reset sandboxes`, `bench` exits with that
  message, and the summary lists the session as incomplete. `cold` still runs there, so a gVisor
  summary with only `cold` numbers means this. See
  [What a pool asks of a profile](pools.md#what-a-pool-asks-of-a-profile).
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

Expect `50 with a verdict, 0 infrastructure failures`, `not what this arm requires: 0` and no warning
about hand-written solutions. A size this small can leave out the smallest classes, and the output's
corpus line says what it holds.

## What a run's result means

A junk or mutated candidate failing verification is the expected result, not a failed run. `bench`
keeps three things apart:

| Count | Meaning | Effect |
|---|---|---|
| Infrastructure failure | Vora failed, or the run has no result: a refusal, a broken stream, an unexpected exit reason, or a completed run where the runner never answered | Counted by cause, left out of latencies and programs per second. The command exits 1 |
| Off shape | A run wasn't warm when the arm requires it, or was warm in the `cold` arm | Counted with its rate, and stays in the latencies because leaving it out would flatter the arm. A warm arm exits 1 only above the bound below, and the `cold` arm exits 1 on one |
| Wrong reuse mode | A run reported a reuse mode its arm doesn't use | Counted. The command exits 1 |
| Program verdict | What `verify` said about the candidate, by candidate index | Reported per class. Doesn't affect the exit code |

**Why a warm arm can run cold.** When a member retires and its destroy returns, Vora gives the freed
slot to the first waiter as a cold start if nothing else is in flight, and that run reports `warm`
false. So a healthy warm arm has at most one cold run per retirement. A member retires only after
`max_runs` runs, warmup included, so the bound is `(candidates + warmup) // max_runs`: 20 for 2,000
candidates, 24 warmup runs and `max_runs` 100. A session long enough to reach `max_age` also gets
`concurrency` more per 30 minutes. Above the bound the arm really is running cold. Each session prints
the count, the rate and the bound, with its `retire_cause` counts and sandbox counts, so you can check
the bound against what happened. A member that retires while idle shows on no run's `retire_cause`.

A fast failure would flatter an arm, so two checks protect the verdicts:

- A hand-written solution that doesn't pass is flagged on that arm alone, with no other arm to compare
  against. These programs are known good, so on `cold` or `warm` the arm is broken and the command
  exits 1. On `warm-no-reset` it is a finding, because a leak can cause it, and the command exits 0.
- The summary compares verdicts and a hash of the outputs by candidate index, across every session of
  the same corpus, and lists every difference at the top. The outputs matter because half the corpus is
  expected to fail: a leak that changes a wrong answer leaves its verdict at `failed`. A difference
  between `cold` and `warm` means an arm is wrong. A difference only with `warm-no-reset` is a finding,
  not an error, and the table says when `cold` or `warm` has no result to check it against. A run with
  no result has nothing to compare. It shows as an infrastructure failure, and its candidate isn't
  compared. A candidate is compared only with a result from every arm that ran its corpus.

`bench-summary` exits 1 on a difference between safe arms, in verdict or outputs, on a hand-written
solution that doesn't pass on `cold` or `warm`, or on a `FAILED` leak suite. It exits 0 otherwise. That
includes a finding on `warm-no-reset`, and an `incomplete`, `stale` or `not run` leak suite, which it
prints loudly, because a partial summary is still useful.

## Run the arms in turn

Each arm gets 5 sessions of 2,000 candidates. A round uses one seed for all three arms, and the arm
order rotates from round to round, so that drift on the host affects all three. Together the rounds
run 10,000 candidates on each arm, and those counts match the mix exactly. Use one raw file per
backend, because a summary compares every session in its file.

Set `CONCURRENCY` to at most half the runner's CPUs: each sandbox has one CPU, and the `cold` arm
reserves twice the concurrency.

```sh
RAW=results/bench/experiment-1-bwrap.jsonl
CONCURRENCY=$(( $(nproc) / 2 ))
arms=(cold warm warm-no-reset)
settle() {
  until awk -v cpus="$(nproc)" '{ exit !($1 <= 0.25 * cpus) }' /proc/loadavg; do sleep 5; done
}
for round in 1 2 3 4 5; do
  for offset in 0 1 2; do
    mode=${arms[$(( (round + offset) % 3 ))]}
    settle
    uv run vora-arc bench --mode "$mode" --seed "$round" --candidates 2000 \
      --concurrency "$CONCURRENCY" --profile profiles/python-arc-bwrap.toml \
      --image-resolved-via containerd --raw "$RAW" || echo "round $round, $mode: exit $?"
  done
done
```

`settle` waits for the 1-minute load to fall to the level the summary's "this machine was busy" warning
fires above, a quarter of the CPUs. A session at this concurrency leaves the load near half the CPUs, so
without the wait most sessions would start under that warning, and it would stop meaning anything. By
the load average's decay this takes under a minute on an otherwise idle host. That is arithmetic, not a
measurement. If `settle` doesn't end, something else is using the host.

The summary records the order the sessions ran in, so you can check the rotation. To run one session
of the spec's full size, omit `--candidates`: it defaults to 10,000. `--warmup` defaults to three times
`--concurrency`. Warmup runs only hand-written solutions, stays out of every measured number and takes
no candidate index.

**How long it takes.** This is an estimate, and this page has no figure because nothing has been
measured. Read the `cold` arm's programs per second from the smoke run above, call it `R`. Then:

```text
10,000 candidates on the cold arm = 10,000 / R seconds
```

The smoke run is small enough to leave out the expensive classes, so treat the result as a lower bound
and add at most 80 / concurrency seconds for them (see [The corpus](#the-corpus)). A busy host or a
different `--concurrency` changes `R`.

Each session appends to the raw file: a header, one line per run, and a footer. Each arm deletes its
pool at the end. A killed `bench` leaves its pool holding capacity. Delete it with the name from the
first lines of output. An answer of 202 means the pool is still draining, and it keeps its route and
its reservation, so repeat until the answer is something else:

```sh
until [ "$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$VORA_API_URL/v1/pools/<name>" \
  -H "Authorization: Bearer $VORA_API_KEY")" != 202 ]; do sleep 2; done
```

Each call waits up to about 25 seconds for running commands. A final answer of 204 or 404 means the pool
is gone. Anything else is an error to read, so run the `curl` once more without `-o /dev/null` to see it.

## Run the leak tests

The experiment reports leak results with its numbers, and `bench` doesn't measure them. Run these
after the bench sessions, on the same host and backend, and keep what they write. Milestone 2 needs
every row of the summary's leak table to say `passed`.

1. Run the pool leak test and its no-reset control. The control skips without
   `VORA_ADMIN_API_KEY`, `VORA_ARC_TENANT_ID` and a runner with `VORA_POOL_UNSAFE_REUSE=allow`.

   ```sh
   VORA_ARC_PROFILE=profiles/python-arc-bwrap.toml uv run pytest tests/test_hostile.py \
     -k 'test_a_write_does_not_survive_into_the_next_run or test_without_a_reset_the_same_write_does_survive' \
     --junitxml results/bench/leak-bwrap.xml
   ```

2. Run Vora's leak suites from a Vora checkout, with the privileges its integration tests need on that
   backend. The first line records which Vora ran, and the summary prints it.

   ```sh
   { echo "vora commit: $(git rev-parse HEAD)"
     go test -v -count=1 -tags=integration -run 'LeakMatrix|TestPoolDisconnectMidRun' ./tests/integration/ 2>&1
   } | tee /path/to/vora-arc/results/bench/vora-leak-bwrap.log
   ```

Repeat both for each backend, with its own files. Keep each file's time if you copy it (`scp -p`):
the summary compares it with the bench sessions.

**What each backend must show.** The summary reads each report for one backend, which you name.

| Backend | pytest report | Vora's log |
|---|---|---|
| `bwrap` | Both tests, each with `write_workspace-0`, `write_root_home-1` and `fill_tmp-2` | `TestBwrapReusableLeakMatrix`, `TestPoolLeakMatrix/bwrap`, `TestPoolDisconnectMidRun/bwrap` |
| `gvisor` | The same | `TestLeakMatrixGvisor`, `TestPoolLeakMatrix/gvisor`, `TestPoolDisconnectMidRun/gvisor` |

`TestBwrapReusableLeakMatrix` is on Vora's `main`. The rest of the log's tests are in
[vorash/vora#153](https://github.com/vorash/vora/pull/153), which is open, so a checkout without that
pull request can't reach `passed`. A row that runs under another backend's name doesn't count, so a
gVisor skip in a bwrap log doesn't matter, and the same log says `incomplete` for `gvisor`.

| Result | Meaning |
|---|---|
| `passed` | Every required test passed, the log ends in `PASS` or `ok`, and the report isn't older than the newest bench session on that backend |
| `stale` | All of that, but the report is older than that session, so it may describe a different server. A junit report's own date counts too |
| `incomplete` | Names what is missing, what skipped, or that the log was cut off with no final line |
| `FAILED` | A required test failed, or the log panicked or ended in `FAIL` |
| `not run` | No report, an unreadable one, or one that names none of the required tests |

## Rebuild the summary

```sh
uv run vora-arc bench-summary results/bench/experiment-1-bwrap.jsonl \
  --leak-pytest bwrap=results/bench/leak-bwrap.xml --leak-vora bwrap=results/bench/vora-leak-bwrap.log
```

The summary reads only the files you give it, and it takes several raw files. A raw file appends, so
it can hold sessions you didn't mean to mix: the summary says when sessions differ in host, commit,
dirty state, server version, memory or warmup. It shows, in order:

1. Candidates that differ in verdict or outputs, safe arms apart from no-reset, and hand-written
   solutions that didn't pass.
2. The leak table, with each report's date and the Vora build its log names.
3. For each arm, over its complete sessions: ordinary programs first and then all classes, each with
   p50, p90, p99, max and count pooled across sessions, and the range of each session's p50 and p99.
   Then the reset's p50 and p99, reset failures, programs per second, and the failure counts. A
   killed session, or one that lost lines, is marked `incomplete`, left out of the pooled figures, the
   ranges and the session count, and listed by name. Its failures still count.
4. Each session: programs per second, p50, p90, p99, max and count for each time, then the same for
   wall-clock for ordinary programs, for all classes and per class, with each class's share of slot time.

Percentiles are nearest-rank, over the runs with a verdict. Programs per second is the runs with a
verdict divided by the measured phase's wall time, which excludes warmup, at the recorded concurrency.

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, so their percentiles cover only the slower runs.
The count that left it out sits next to them, and a row with more left out than reported shows
`under half reported` instead of a percentile. The client's own startup time has no such gap.

A reset failure retires its member, and the next run can still report warm on a new one, so it doesn't
show as off shape. The top table counts reset failures and makes a nonzero count bold. They don't change
`bench`'s exit code unless the cold runs they cause go above the bound.

## What limits each arm's number

`wall_ms` runs from sending the request to reading the `exit` frame, on the client's clock.
`cycle_ms` goes on to the end of the stream, so it includes the reset. Latency comes from `wall_ms`
and programs per second reflects `cycle_ms`, so read both.

**`cold`.** A sandbox start dominates. `startup_ms` is the borrow wait plus the start. If the image
isn't in containerd, every start also carries a registry attempt (#148).

`cold` is a pool of size 0, not a `force_cold` flag. Vora has no such flag, because a size-0 pool is
its way to bypass reuse. That adds three differences to a plain cold start:

- A size-0 pool goes through the pool's borrow path, so its runs carry that small cost too.
- `MemberSpec` sets `DenyIPC = reused()`, which is false at size 0. A `cold` sandbox doesn't deny SysV
  and POSIX IPC, and it captures no reset manifest, so it skips work the other arms do at start. The
  arms therefore differ in more than the pool's shape.
- A retired member keeps its slot until its destroy returns. With `max_size` equal to the concurrency,
  a run would wait for the previous run's destroy, and `startup_ms` would include that wait. So `bench`
  declares `max_size` as twice the concurrency, and the next start overlaps the destroy. The wait comes
  back only if more than a concurrency's worth of destroys are outstanding at once, and it then shows
  in `startup_ms`. The destroy still uses host CPU, which shows as contention on later runs.

**`warm`.** The program's own run dominates `wall_ms`: the runner starts a Python interpreter for each
run. The reset falls outside `wall_ms`, but the client holds its slot until `run_done`, so the reset
lowers programs per second. On gVisor, in the code of vorash/vora#150 as measured in that work's build
log, a reset starts `runsc` three times. Check this again on the release you run. A member retires after
100 runs, or at the default `max_age` of 30 minutes. With `size` equal to `max_size`, its replacement
starts only once its destroy returns. Until then a borrower waits for another member, and the wait
shows in `startup_ms`. If nothing else is in flight when the destroy returns, the borrower starts cold
instead and the run counts as cold ([Why a warm arm can run cold](#what-a-runs-result-means)). With
`max_runs` 100, about 1 run in 100 follows a retirement, so `warm`'s p99 can sit on this path. That is
arithmetic, not a measurement. Every arm sets `borrow_timeout_ms`
to 60 seconds, so a slow replacement shows as a slow run. A longer wait is a refusal, and that is an
infrastructure failure.

**Which way the shapes bias the gap: they narrow it.** Three differences favour `cold`, so the measured
gap between `cold` and `warm` is smaller than what a cold start really costs:

- `cold` has twice the slots, so its next start overlaps the previous destroy. `warm` has no such slots:
  a retired member holds its slot until its destroy returns, and its replacement starts only then.
- `cold`'s destroy runs after `run_done`, so no run's `cycle_ms` holds it. It shows only as contention.
  `warm`'s wait for a destroy shows in `startup_ms`.
- A `cold` sandbox doesn't deny IPC and captures no reset manifest, as listed above.

Giving `warm` twice the slots too wouldn't remove the wait. Vora starts a replacement only when the
destroy returns (`Pool.remove`), and with a run in flight a borrower queues whatever slots are free. The
simulation behind this ran Vora's real pool code against fake sandboxes with made-up durations, and
doubling `max_size` left the cold-run counts about the same, so it is no measurement of a host. It would
also double what `warm` reserves. So the shape stays, and this bias stays in the numbers.

**`warm-no-reset`.** It runs what `warm` runs, minus the reset, so the gap to `warm` is the reset's cost
and nothing more. The speed comes from leaving one run's files and processes for the next, which is
why the reset exists. `test_without_a_reset_the_same_write_does_survive` shows the leak. Every output
of this arm says `UNSAFE`. Don't quote its number as something a pool can deliver safely. Its verdicts
matching the other arms' doesn't make it safe: nothing in the corpus tries to leave state behind.

**All arms.**

- The client can be the limiter. It is one Python process parsing every chunk. The footer records its
  CPU over the measured window alone, without warmup or the pool's delete, and the summary warns when
  that passes 50% of the window's wall time. Near 100% you measured the client, and queueing in its
  event loop starts before that.
- httpx keeps 20 idle connections by default, so above concurrency 20 a slot would reconnect for each
  run. `client.connect` turns those limits off, so this adds no reconnects at any concurrency.
- Each sandbox has one CPU, so concurrency above the host's core count measures contention.
- Check the arithmetic: programs per second can't exceed the concurrency times 1000 divided by the
  mean `cycle_ms`. A figure above that measured something else.
- The corpus limits the number too. A class's share of slot time says where the time went on each arm.
- `bench` doesn't find what limits a run. Profile the host in a separate run, and don't report that run.

## How `bench` answers the benchmark checklist

| Question | What `bench` does | What is left to you |
|---|---|---|
| Did it error? | Counts every refusal, broken stream and bad exit as an infrastructure failure, by cause. Retries nothing | Read the counts |
| Did it even happen? | Runs `verify` on each result and records a hash of its outputs. Compares verdicts and hashes across arms by candidate index, and flags a hand-written solution that doesn't pass | Expect no differences |
| Does it reproduce? | Shows each arm's median and range across sessions, and says when there are fewer than 5. Each session in the loop above has its own seed, so that range includes differences between corpora with the same mix | Run the loop above. A gap inside the range is no measurable difference |
| Was it tuned? | Uses the profile's limits on every arm. `borrow_timeout_ms` is 60 s, where `solve --pool` keeps Vora's default of 2 s | Use a host like the one you care about |
| Why not double? | Records load, CPU count and client CPU | Find the limiter with a profiler |

`bench` measures with its own clock and doesn't read `runs_total`, because that counter counts a run
whose client left before its exec ([vorash/vora#149](https://github.com/vorash/vora/issues/149)).
