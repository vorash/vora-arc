# Model pipeline

`solve` handles one task at a time. Sandbox jobs for a task run concurrently under
`VORA_MAX_CONCURRENCY`, so the cap also holds for the whole run.

| Module | Job |
|---|---|
| `generate` | Build the prompt, sample completions through the cache, extract programs |
| `schedule` | Run a task's distinct programs (asyncio now; Ray would replace this one module) |
| `verify` | Judge one run (from Milestone 1, unchanged) |
| `vote` | Choose up to two answers |
| `refine` | Build the second-round prompt |
| `pipeline` | Tie those together for one task, with no database |
| `store` | PostgreSQL |
| `report` | Markdown and charts from one stored run |

## Decisions

- **The prompt hash covers the model, temperature and token limit,** so changing
  any of them samples again. The cache key stays `(task_id, prompt_hash, sample_index)`.
- **Stored task ids carry the dataset,** as in `arc1/007bbfb7`. ARC-AGI-1 and
  ARC-AGI-2 share 773 ids, and the grids differ on every one.
- **Duplicates vote.** A program the model wrote three times runs once and counts
  as three votes, because the count measures how often the model reached an answer.
- **A task with several test inputs is answered as a whole.** One answer is one
  output per test input, and it's correct only if all of them are. This matches the
  spec's `answers` table. It is stricter than scoring each test input on its own,
  and it affects the 33 of 400 ARC-AGI-1 training tasks with several test inputs.
- **A passed candidate whose test input failed can't vote,** because a verdict
  looks only at the train pairs.
- **A Vora failure isn't a verdict.** The candidate keeps a NULL verdict and an
  `infra_error`, the report counts it separately, and `solve` exits non-zero.
- **A model outage fails the run and keeps what finished.** Completions and finished
  tasks stay stored, and the next run requests only what's missing.

## Tables added to the spec's

| Addition | Why |
|---|---|
| `solve_runs` | One row per `solve`, with its settings and status. This is the run id. The spec's `runs` table means sandbox runs |
| `candidates.run_id`, `answers.run_id` | Tell runs apart. `completions` has no run id, because the cache crosses runs |
| `candidates.sample_index`, `prompt_hash` | Link a candidate to its completion, and let a report re-vote on the first k samples |
| `candidates.infra_error` | A Vora failure, which has no verdict |
| `answers.round` | Accuracy by round |
| `runs.id`, `attempt`, `exec_ms` | Tell the determinism re-run apart, and measure execution |
| `task_phases` | Generation, scheduling and verification time per task and round |

## Reading a report

Accuracy vs candidate count re-votes round 1 on the first k samples of each task.
A shorter run with the same cache would see exactly those samples. A count above the
run's `--samples` is "not measured", and refinement isn't included.

GPU-hours are the time this run had a model request open. Idle GPU time isn't
counted. A run served from the cache logged no generation, so its cost is "not
measured", not zero.

## Verified

Against the fake model, real PostgreSQL and real sandboxes on vora-mini, under both
`python-arc` (gVisor) and `python-arc-bwrap`: every verdict, duplicates, refinement,
a real ARC task, the second run making no model request, and every sandbox destroyed.
Run it with `uv run pytest -m sandbox`.

## Not verified until a real model exists

- How often a real model's completions extract, and whether a 4096-token limit is enough.
- Any accuracy, generation time or cost figure.
- The request shape on vLLM itself: `/chat/completions` with `n` up to 16.

## Not verified until warm pools exist

- `runs.warm_start` is always false, and `reset_ms` and `audit_log_id` are NULL. The
  current client can't see an execution id, and a fresh sandbox has no reset.
- The dashboard's Pool state panels use the design's `vora_pool_*` names. Vora doesn't
  export them yet, so these panels stay empty.
