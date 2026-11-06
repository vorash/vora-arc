# Model pipeline

`solve` handles one task at a time unless `--tasks-at-once` says otherwise. Sandbox jobs
run concurrently under `VORA_MAX_CONCURRENCY`, and tasks share that cap, so it holds for
the whole run. They also share a limit of 8 open model requests.

Use `--tasks-at-once` on a real model. A request lasts as long as its longest sample, so
a runaway sample at the 4096-token limit would otherwise keep the GPU almost idle for
minutes, with every later task waiting behind it.

| Module | Job |
|---|---|
| `generate` | Build the prompt, sample completions through the cache, extract programs |
| `schedule` | Run a task's distinct programs (asyncio now; Ray would replace this one module), on a fresh sandbox or a pool |
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
  `infra_error`, and `solve` exits non-zero. The report counts the tasks it hit, says
  they can't be judged, and shows accuracy both with and without them.
- **A refine prompt too long for the model leaves the first round standing.** The prompt
  shows three programs and a diff per example, so a big task's can outgrow the model's
  context. The model's refusal is logged, and the report's round 2 line counts only the
  tasks that got a round 2. Any other refusal still stops the run.
- **A model outage fails the run and keeps what finished.** Completions and finished
  tasks stay stored, and the next run requests only what's missing.
- **A report scores against the task as that run solved it.** The task goes into
  `solve_run_tasks` in the same transaction as its answers. After a task file is
  corrected, older runs keep their score, and cached completions stay valid unless the
  prompt changed, because a test output never reaches the model.
- **A sample has one text.** When two runs race for a sample, the first text saved is
  the one both runs judge, so a candidate always matches the completion it points at.
- **Credentials in `VLLM_URL` never stay in the URL.** httpx logs and raises the URL it
  was given, so they travel as Basic auth instead.
- **A bug in one job cancels the task's other jobs.** Each destroys its sandbox before
  the error reaches `solve`, including a sandbox still being created.
- **Ctrl-C closes the run as `interrupted`.** `running` means the run is still live, or
  that its process was killed without a chance to record that (SIGTERM, SIGKILL, power).

## Tables added to the spec's

| Addition | Why |
|---|---|
| `solve_runs` | One row per `solve`, with its settings and status (`running`, `finished`, `failed`, `interrupted`). This is the run id. The spec's `runs` table means sandbox runs |
| `solve_run_tasks` | Each task as that run solved it. The spec keeps the JSON on `tasks`, where the first definition of an id would win forever, so `tasks` holds only ids here |
| `candidates.run_id`, `answers.run_id` | Tell runs apart. `completions` has no run id, because the cache crosses runs |
| `candidates.sample_index`, `prompt_hash` | Link a candidate to its completion, and let a report re-vote on the first k samples |
| `candidates.infra_error` | A Vora failure, which has no verdict |
| `answers.round` | Accuracy by round |
| `runs.id`, `attempt`, `exec_ms` | Tell the determinism re-run apart, and measure execution |
| `task_phases` | Generation, scheduling and verification time per task and round |

The schema is `CREATE TABLE IF NOT EXISTS`, with no migrations, so a change to an
existing table reaches only a new database.

## Reading a report

Accuracy vs candidate count re-votes round 1 on the first k samples of each task.
A shorter run with the same cache would see exactly those samples. A count above the
run's `--samples` is "not measured", and refinement isn't included.

Cost has two bases, and the report names both:

| Basis | Formula | Meaning |
|---|---|---|
| Wall-clock | `(finished_at - started_at)` x price | What a rented GPU costs for this run, because a rental bills idle time too. A run that didn't finish has no such figure |
| Request time | Time with a model request open x price | The lower bound. A failed run's unfinished task isn't logged, so its requests aren't counted |

Cost per task divides each by the run's tasks. It is "not measured" if any completion
came from the cache, because an earlier run paid for that completion. A run served
entirely from the cache has no GPU time to bill, so its cost is "not measured", not zero.

Accuracy counts a task Vora failed on as voted, on the candidates that got a verdict.
A second column leaves those tasks out of both sides of the fraction. Neither column
is what the model would have scored without the failures.

`load_run` reads only the test grids of passed candidates, because a report votes on
nothing else.

## Verified

Against the fake model, real PostgreSQL and real sandboxes on vora-mini, under both
`python-arc` (gVisor) and `python-arc-bwrap`: every verdict, duplicates, refinement,
a real ARC task, the second run making no model request, every sandbox destroyed, and
Ctrl-C with sandboxes running.
Run it with `uv run pytest -m sandbox`.

## Not verified until a real model exists

- How often a real model's completions extract, and whether a 4096-token limit is enough.
- Any accuracy, generation time or cost figure.
- The request shape on vLLM itself: `/chat/completions` with `n` up to 16.

## Verified on a real pool

`vora-arc bench` ran on real pools for [experiment 1](experiment-1-results.md), and `solve --pool` runs on
real pools in `tests/test_solve_e2e.py`, both on vora-mini under both backends. See
[About warm pools](pools.md).

The dashboard's pool panels use the names in Vora's `internal/telemetry/metrics.go`, and
`tests/test_dashboard.py` checks them against that file. While a pool ran on vora-mini, the runner served
those series with real values on both backends, except `vora_pool_retired_total` and
`vora_pool_not_loaded`, which didn't appear at that moment. Vora removes a pool's series when the pool is
deleted. No Grafana has drawn these panels yet.
