# Run 20261106T142133Z-bcc15e

- Dataset: arc1 evaluation, 100 tasks (limit 100)
- Model: mistralai/Mistral-7B-Instruct-v0.3; 64 samples per task; refinement off
- Sandbox: profile python-arc, backend gvisor, at most 8 at a time; 8 task(s) at once
- Status: finished
- Total wall-clock: 13141.340 s

## Accuracy

| | Solved |
|---|---|
| Overall, 2 attempts | 0 / 100 (0.0%) |
| Round 1, of all tasks | 0 / 100 (0.0%) |
| Round 2, of the tasks it refined | not measured (run without --refine) |

4 tasks have several test inputs. Each counts as solved only if one answer gets all of them right.

## Accuracy vs candidate count

Round 1, re-voted on the first k samples of each task in this run. Refinement isn't included. A count above this run's 64 samples is not measured.

| Candidates per task | Solved |
|---|---|
| 16 | 0 / 100 (0.0%) |
| 32 | 0 / 100 (0.0%) |
| 64 | 0 / 100 (0.0%) |
| 128 | not measured |

![accuracy](accuracy_vs_candidates.png)

## Verdicts

6400 candidates, 6366 distinct programs, 6366 sandbox runs. A duplicate counts under its first copy's verdict.

| Verdict | Candidates |
|---|---|
| unparseable | 22 |
| timeout | 14 |
| crashed | 4099 |
| invalid | 687 |
| failed | 1578 |
| memorized | 0 |
| nondeterministic | 0 |
| passed | 0 |

![verdicts](verdicts.png)

## Time split

| Phase | Time | Basis |
|---|---|---|
| generation | 37597.949 s | sum over tasks that overlap, so it can exceed the run's wall-clock |
| scheduling | 5996.847 s | sum over jobs of the wait for a slot |
| startup | 119.753 s | sum over sandbox runs, seen from the client |
| execution | 1369.705 s | sum over sandbox runs, seen from the client |
| verification | 140.973 ms | sum over jobs of verdict and vote computation |
| reset | 266.514 s (6366 of 6366 runs used a pool's running sandbox and the rest a fresh one; 6327 of 6366 reported a reset of their own) | sum over sandbox runs |

Sums over jobs overlap when jobs run at once, so they don't add up to the wall-clock.

## Policy events

- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured. This solver doesn't read them. Vora's `egress_denied` exists only in restricted mode, where it is a floor, and pools refuse that mode.

## Cost

- Wall-clock, what a rented GPU costs for this run: 3.650372 GPU-hours, 2.874668 EUR
- Time with a model request open, the lower bound: not measured
- Cost per task: 0.028747 EUR on wall-clock, not measured as the lower bound
- Price: 0.7875 EUR per hour
- Note: the lower bound is not measured: tasks overlapped, so their request times can't be added
