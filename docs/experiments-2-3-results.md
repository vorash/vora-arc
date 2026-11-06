# Experiments 2 and 3 results

Mistral 7B solved none of the first 100 ARC-AGI-1 evaluation tasks at 64 samples per task, and none of
its 6,378 programs passed a task's train pairs. On 12 hand-picked simple tasks, the same pipeline solved
7, so the zero comes from the model and its prompt, not from the pipeline. The run cost 2.87 EUR. Sandbox
time would be 13% of the wall-clock even if no two sandboxes overlapped, so generation set the run's length.

These are single runs of one small model with a plain prompt on one rented GPU. They don't describe what
other models or prompts can do, or what other hardware can do. I chose the L4 for its cost.

## Setup

| | |
|---|---|
| Date | 2026-11-06 |
| Model | Mistral 7B Instruct v0.3, revision `c170c708c41dac9275d15a8fff4eca08d52bab71`, temperature 0.8, at most 4,096 tokens per sample, not seeded |
| Prompt | The train pairs and test inputs as digits, and a request for one `transform` function. No worked examples |
| Server | vLLM v0.32.0, `--max-model-len 32768 --gpu-memory-utilization 0.9`, on a Scaleway L4-1-24G in `pl-waw-2`: NVIDIA L4, 23,034 MiB, driver 580.178.04, 0.7875 EUR per hour |
| Sandbox | Vora v0.10.8 on vora-mini, gVisor, profile `python-arc`, a warm pool of 8 |
| Client | `solve --pool --tasks-at-once 8` on a third machine, with SSH tunnels to the GPU and to Vora |
| vora-arc | `0475311` for the first two runs below, `2dd83e0` for the last three |

## The runs

| Run | Tasks | Samples | Solved | Programs that passed | GPU time, cost |
|---|---|---|---|---|---|
| [`20261106T142133Z-bcc15e`](../results/l4-2026-11-06/20261106T142133Z-bcc15e/report.md) | ARC-AGI-1 evaluation, first 100 by id | 64 | 0 / 100 | 0 | 3.65 h, 2.87 EUR |
| [`20261106T180456Z-69613b`](../results/l4-2026-11-06/20261106T180456Z-69613b/report.md) | ARC-AGI-2 evaluation, first 20 by id | 64 | 0 / 20 | 0 | 1.12 h, 0.88 EUR |
| [`20261106T191234Z-ba739a`](../results/l4-2026-11-06/20261106T191234Z-ba739a/report.md) | ARC-AGI-1 evaluation, first 20 by id, with refinement | 64 cached + 32 new | 0 / 20 | 0 | 0.64 h, 0.50 EUR |
| [`20261106T195116Z-adb599`](../results/l4-2026-11-06/20261106T195116Z-adb599/report.md) | ARC-AGI-1 training, 12 hand-picked simple tasks | 64 | 7 / 12 | 25 | 0.11 h, 0.08 EUR |
| [`20261106T195806Z-cff43e`](../results/l4-2026-11-06/20261106T195806Z-cff43e/report.md) | ARC-AGI-1 training, first 20 by id | 64 | 0 / 20 | 0 | 0.55 h, 0.43 EUR |

The control's 7 of 12 is not an accuracy estimate. I picked its tasks for their simple rules, such as a
flip, a rotation or a colour swap, to find out whether a real model could get through the whole path.
Those tasks are `0d3d703e 25ff71a9 3c9b0459 6150a2bd 67a3c6ac 68b16354 74dd1130 a416b8f3 b1948b0a
c8f0f002 d511f180 ed36ccf7`. Every answer the 25 passing programs voted for was correct.

## Why the zero is the model

- **The pipeline can solve a task.** The control took real completions through the sandbox, verdict, vote
  and test-output check. Separately, [the hand-written solutions](milestone-1.md) reach `passed` under both
  backends.
- **A match can't be lost at the comparison.** A program whose output equals the expected grid would score
  a cell accuracy of 1.0. The highest in the 100-task run is 0.989.
- **The completions are real attempts.** 6,378 of 6,400 held an extractable program, and only 2.5% hit the
  token limit. The errors are the model's own, for example reshaping a 4-cell array to `(4, 4)`.

| Verdict, 100-task run | Candidates | Share |
|---|---|---:|
| crashed | 4,099 | 64.0% |
| failed: ran, but got a train pair wrong | 1,578 | 24.7% |
| invalid: returned something that isn't a grid | 687 | 10.7% |
| unparseable | 22 | 0.3% |
| timeout | 14 | 0.2% |
| passed | 0 | 0% |

A high cell accuracy doesn't mean a program is nearly right, because a grid that is mostly background can
score well without the rule. 18 of the 100 tasks reached 0.9, and none was solved.

I didn't try other prompts or models. Worked examples or a stronger model are the obvious next tests, and
this run says nothing about how much either would help.

## Experiment 2: accuracy by candidate count and refinement

The counts below are the first k samples of each task, re-voted, so they come from one run.

| Candidates per task | First 100 evaluation tasks | Control, 12 tasks |
|---:|---:|---:|
| 16 | 0 / 100 | 5 / 12 |
| 32 | 0 / 100 | 7 / 12 |
| 64 | 0 / 100 | 7 / 12 |
| 128 | not measured | not measured |

I didn't run 128 samples because they would double the generation time, to about 7.3 hours by my estimate
for the same 100 tasks. The control is the only run where the count changed anything.

Refinement ran on 20 tasks and solved none, so this experiment can't say whether it helps. One task,
`05a7bcf2`, wasn't refined because its 48,874-token prompt is over the model's limit. The second round
did produce more programs that run:

| Verdict, same 20 tasks | Round 1 (1,280) | Round 2 (608) |
|---|---:|---:|
| crashed | 62.3% | 42.6% |
| failed | 25.3% | 50.5% |
| invalid | 12.0% | 5.6% |
| unparseable or timeout | 0.4% | 1.3% |
| passed | 0% | 0% |

Of the 19 refined tasks, the best cell accuracy rose on 3, fell on 2 and held on 14. The mean of each
task's best went from 0.583 to 0.601.

## Experiment 3: where time and money go

**Generation sets the run's length.** In the 100-task run, sandboxes spent 1,756 s on startup, execution and
reset, against a wall-clock of 13,141 s. That share is 13% if they never overlapped and 1.7% if all 8 slots
were always busy. The run asked for 0.48 programs
per second, about 1% of the 44.1 per second that [experiment 1](experiment-1-results.md) measured for a warm
gVisor pool on the same host, with no tunnel. The GPU averaged 99.8% busy.

| Sandbox time per run, 100-task run | p50 | p99 |
|---|---:|---:|
| Execution | 196 ms | 245 ms |
| Reset | 42 ms | 51 ms |

Startup has a p50 of 14 ms. Each program also waited about 0.9 s on average for a slot, because all of a
task's programs arrive together.

**Longer prompts slow generation.** Across the five runs, output throughput falls as prompt tokens per sample
rise, and at 2,330 tokens and above, the KV cache stays over 70% full. This is an association across
single runs with different tasks, not a controlled test. The rate at the top is above the 490 tokens/s
that the server's benchmark reached at saturation with a separate prompt per request. I didn't isolate why.
My guess is that samples of one prompt share its blocks and its processing.

| Run | Prompt tokens per sample | Output tokens per sample | Output tokens/s | KV cache, mean | Waiting, mean | Preemptions |
|---|---:|---:|---:|---:|---:|---:|
| Control | 321 | 315 | 631 | 28% | 0 | 0 |
| ARC-AGI-1 training, first 20 | 2,330 | 574 | 352 | 72% | 0.3 | 80 |
| ARC-AGI-1 evaluation, first 100 | 3,539 | 634 | 309 | 83% | 6.1 | 4,150 |
| ARC-AGI-2 evaluation, first 20 | 5,030 | 800 | 254 | 86% | 13.0 | 954 |
| Refinement, round 2 | 12,610 | 497 | 132 | 83% | 65.5 | 466 |

These figures come from Prometheus `increase` over each run's window, saved as `gpu-metrics.json` beside each
report, so they are close but not exact. Preemptions count requests that lost their KV cache blocks and had
to start again. In the 100-task run, 162 samples (2.5%) ran to the 4,096-token limit. I estimate they took
about 16% of the output tokens, since 162 × 4,096 is about 664,000 of 4.06 million.

**Money.** The 100-task run cost 0.029 EUR per task, or 131 s of GPU per task with 8 tasks at once. By extrapolation, all 400
evaluation tasks would take about 14.6 hours and 11.50 EUR. That wasn't run. The machine
ran for 439 minutes, about 5.76 EUR at the listed price, which I haven't compared with an invoice. Of that,
the five runs account for 4.77 EUR. Setup, the benchmark and a trial took the rest.

## Sandbox behaviour

The five runs made 11,500 sandbox runs of model-written code, including the first-round programs that the
refinement run ran again. There were 0 infrastructure errors, and Vora listed no pool after any run. 35 runs
were killed at the 256 MiB limit and 9 at their time limit, and each was recorded as a verdict without
stopping the run. Vora reported `POOL_RESET_FAILED` after all 35 of those memory kills, and
`POOL_RESET_RETIRED`, with no reset, after 59 runs at a sandbox's 100-run limit. All the others reset.

## What these results leave out

- **The whole evaluation set.** The 100 tasks are the first by id, a fixed subset of the 400.
- **Repeats.** Each configuration ran once, and sampling isn't seeded, so a new run will write different
  programs.
- **Time with a request open.** Tasks overlapped, so reports give that lower bound as not measured.
- **The start of the ARC-AGI-2 run's timing.** A 30,000-token probe of mine with 16 samples occupied the model
  for up to 60 s just after that run began. It can't have changed the accuracy, and it's small against 4,035 s.
- **Prompts near the limit.** vLLM refused prompts over 32,768 tokens. Two refinement prompts in the first 20
  tasks, on `0934a4d8` and `09c534e7`, were under that limit but left less than 4,096 tokens for output. I didn't
  check how vLLM handled those requests.
- **The benchmark's setting.** The benchmark table for this server was measured with `--max-model-len 8192`.
  These runs used 32768. The KV cache was 45,136 tokens before that change and 45,120 after it.

## Files

Everything is under `results/l4-2026-11-06/`.

| Path | What it holds |
|---|---|
| `vora_arc.dump` | The PostgreSQL database of all five runs, including every completion and sandbox result. The reports regenerate from it byte for byte |
| `<run id>/report.md`, `*.png` | `vora-arc report` output |
| `<run id>/gpu-metrics.json` | vLLM and GPU metrics for the run's window, with the queries. Their source was deleted with the machine |
| `logs/` | Each run's console output, with elapsed seconds |
