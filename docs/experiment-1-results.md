# Experiment 1 results

A warm pool with a reset runs 3.1 times as many programs per second as a new sandbox per program on
bwrap, and 1.8 times as many on gVisor. The reset costs 6% of warm throughput on bwrap and 24% on
gVisor. Every leak test passed on both backends, and the control shows that skipping the reset does
leak.

These numbers describe one small host at one concurrency. They aren't a capacity claim for other
hardware. [How to run experiment 1](experiment-1.md) has the method and what limits each arm.

## Setup

| | |
|---|---|
| Date | 2026-11-06 |
| Host | vora-mini: AMD Ryzen 7 5825U, 8 cores, 16 threads, 26 GB. `bench` ran on the host, not through a tunnel |
| Vora | v0.10.8 |
| vora-arc | `272e731`, clean tree, Python SDK 0.8.0 |
| Runs | 15 sessions per backend: 5 per arm, 2,000 candidates each, seeds 1 to 5, arm order rotated. 10,000 candidates per arm |
| Concurrency | 8 |
| Limits | The same profile on every arm: 1 CPU per sandbox, network `none` |
| Failures | 0 infrastructure failures, 0 off-shape runs and 0 reset failures in 60,000 runs |

## Results

Latency is wall-clock from request to exit, pooled over ordinary programs, which leaves out the `slow`,
`memory_hungry` and `timeout` classes. Programs per second covers all classes, and shows the median
session with the range of all 5.

| Backend | Arm | Programs/s (range) | p50, ms | p99, ms | Reset p50 / p99, ms |
|---|---|---|---|---|---|
| bwrap | cold | 33.4 (33.4 to 33.5) | 229.6 | 279.1 | none |
| bwrap | warm | 104.6 (104.2 to 105.3) | 64.1 | 94.0 | 3 / 6 |
| bwrap | warm-no-reset (unsafe) | 111.3 (109.1 to 112.1) | 63.2 | 91.4 | skipped |
| gVisor | cold | 24.3 (24.3 to 24.4) | 317.8 | 368.9 | none |
| gVisor | warm | 44.1 (43.8 to 44.3) | 122.3 | 196.2 | 46 / 56 |
| gVisor | warm-no-reset (unsafe) | 58.3 (57.7 to 58.4) | 123.7 | 187.4 | skipped |

`warm-no-reset` is a control. It leaves one run's files and processes for the next, so its number isn't
something a pool can safely deliver.

### Leak tests

| Suite | bwrap | gVisor |
|---|---|---|
| A write doesn't survive a reset (`test_a_write_does_not_survive_into_the_next_run`) | 3 of 3 passed | 3 of 3 passed |
| With no reset, the same write does survive (`test_without_a_reset_the_same_write_does_survive`) | 3 of 3 passed | 3 of 3 passed |
| Vora's leak matrices and disconnect test | 31 of 31 passed | 47 of 47 passed |

The Vora suites ran from `4260c8c`, which differs from v0.10.8 only in tests and docs. Each report is newer
than the last bench session on its backend.

Within each backend, the 10,000 candidates got the same verdict and the same output hash in every session
on every arm. That includes the unsafe arm, and it says nothing about that arm's safety: nothing in the
corpus tries to leave state behind. The leak tests answer that.

On the `warm` arm, bwrap and gVisor also agreed with each other on all 10,000, in verdict and output hash.

## Where the time goes

The table gives medians over ordinary programs, in ms, and the mean reset. `Before start` is from sending the request to
the `run` frame. `Exec` is from the `run` frame to `exit`.

| Backend | Arm | Before start | Exec | Reset, mean |
|---|---|---|---|---|
| bwrap | cold | 174.9 | 54.7 | none |
| bwrap | warm | 2.9 | 60.6 | 3.1 |
| bwrap | warm-no-reset | 2.9 | 59.7 | none |
| gVisor | cold | 170.7 | 146.1 | none |
| gVisor | warm | 15.5 | 106.3 | 46.1 |
| gVisor | warm-no-reset | 15.6 | 107.6 | none |

Three things follow:

- **The arithmetic holds.** On every arm, programs per second is within 1% of the limit that 8 slots and
  the mean cycle time allow. On bwrap, 8 x 1000 / 75.8 ms is 105.5 against 104.7 measured overall.
- **The reset explains the gap to the control.** A warm cycle takes 4.3 ms longer than a no-reset cycle on
  bwrap, and 44 ms longer on gVisor. The reset itself means 3.1 ms and 46.1 ms. It runs after the exit
  frame, so it lowers throughput and leaves latency within about 1 ms.
- **A warm pool removes the wait, not the work.** On bwrap, nearly all of the cold arm's extra time is
  before the start. On gVisor a first run in a new sandbox also takes about 40 ms longer than a run on a
  warm member. We haven't found out why.

## What limits it

These findings come from separate runs on the same host, and those runs are in no number above. They used 200 to 2,000
runs, so their programs per second isn't comparable with the table.

**A warm run's floor is the runner's Python process, not Vora.** Each command ran 200 times on one slot and one member:

| Command | bwrap p50, ms | gVisor p50, ms |
|---|---|---|
| `true` | 3.2 | 12.2 |
| `python3 -c pass` | 12.8 | 28.5 |
| The runner with a hand-written solution | 40.9 | 75.6 |

A program that fails to parse takes as long as one that runs (63.7 and 63.9 ms at p50 on bwrap, at
concurrency 8), so the candidate's own work is a small part of this corpus's time.

**Above that, the limit is the host's CPU.** Exec time rises with concurrency:

| Concurrency | bwrap exec p50, ms | gVisor exec p50, ms |
|---|---|---|
| 1 | 39.6 | 64.1 |
| 4 | 48.0 | 79.8 |
| 8 | 61.8 | 108.0 |
| 16 | 100.5 | 171.2 |

At concurrency 16 the host had 16% idle on bwrap and 17% on gVisor, over 8 s of `vmstat`. To rule out the
client and the pool, two client processes ran two pools at concurrency 8 each on bwrap. Together they reached
129 programs per second, against 126 for one client at 16, with about the same exec p50 (101.1 and 100.4 ms),
so neither the client nor the pool is the limit. Concurrency 8 is one sandbox per physical core. The experiment's
numbers already include this contention.

## How to read it

- **The corpus affects every number.** Most programs here do little work, so startup and reset weigh more
  than they would for slow programs. The gap between arms would narrow as programs take longer.
- **The shapes favour `cold`.** So the measured gap is smaller than what a cold start really costs. See
  [Which way the shapes bias the gap](experiment-1.md#what-limits-each-arms-number).
- **Model and GPU costs aren't here.** This measures running a candidate, and no model took part.
- **One session started above the load the summary warns about.** A bwrap `warm` session started at load 4.9
  on 16 CPUs. Its 105.3 programs per second is within that arm's range. The 5 sessions per arm vary by at
  most 3% in programs per second.

## The files

Every number on this page comes from a file in `results/`:

| Path | What it holds |
|---|---|
| `results/bench/experiment-1-bwrap.jsonl`, `experiment-1-gvisor.jsonl` | One line per run, with each session's header and footer |
| `results/bench/summary-bwrap.md`, `summary-gvisor.md` | `bench-summary` over those files and the leak reports |
| `results/bench/leak-*.xml`, `vora-leak-*.log` | The leak reports |
| `results/bench/exp-*.log` | `bench`'s output for each session |
| `results/limiter/one-slot.txt`, `vmstat.txt`, `host.txt` | The floor table, the idle share and the host's CPU |
| `results/limiter/bwrap-c*.jsonl`, `gvisor-c*.jsonl`, `limiter-sweep.txt` | The concurrency sweep |
| `results/limiter/logged-*.jsonl` | One client at 16 and two clients at 8 |
| `results/limiter/limiter.py`, `decomp.py` | The scripts behind the floor table and the time breakdown |

To rebuild a summary, see [Rebuild the summary](experiment-1.md#rebuild-the-summary).
