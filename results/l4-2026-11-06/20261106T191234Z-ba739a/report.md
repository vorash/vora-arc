# Run 20261106T191234Z-ba739a

- Dataset: arc1 evaluation, 20 tasks (limit 20)
- Model: mistralai/Mistral-7B-Instruct-v0.3; 64 samples per task; refinement on
- Sandbox: profile python-arc, backend gvisor, at most 8 at a time; 8 task(s) at once
- Status: finished
- Total wall-clock: 2291.644 s

## Accuracy

| | Solved |
|---|---|
| Overall, 2 attempts | 0 / 20 (0.0%) |
| Round 1, of all tasks | 0 / 20 (0.0%) |
| Round 2, of the tasks it refined | 0 / 19 (0.0%) |

## Accuracy vs candidate count

Round 1, re-voted on the first k samples of each task in this run. Refinement isn't included. A count above this run's 64 samples is not measured.

| Candidates per task | Solved |
|---|---|
| 16 | 0 / 20 (0.0%) |
| 32 | 0 / 20 (0.0%) |
| 64 | 0 / 20 (0.0%) |
| 128 | not measured |

![accuracy](accuracy_vs_candidates.png)

## Verdicts

1888 candidates, 1840 distinct programs, 1840 sandbox runs. A duplicate counts under its first copy's verdict.

| Verdict | Candidates |
|---|---|
| unparseable | 8 |
| timeout | 5 |
| crashed | 1057 |
| invalid | 187 |
| failed | 631 |
| memorized | 0 |
| nondeterministic | 0 |
| passed | 0 |

![verdicts](verdicts.png)

## Time split

| Phase | Time | Basis |
|---|---|---|
| generation | 9854.285 s (covers 608 of 1888 completions; the rest came from the cache) | sum over tasks that overlap, so it can exceed the run's wall-clock |
| scheduling | 5375.001 s | sum over jobs of the wait for a slot |
| startup | 36.113 s | sum over sandbox runs, seen from the client |
| execution | 411.132 s | sum over sandbox runs, seen from the client |
| verification | 47.221 ms | sum over jobs of verdict and vote computation |
| reset | 77.384 s (1840 of 1840 runs used a pool's running sandbox and the rest a fresh one; 1828 of 1840 reported a reset of their own) | sum over sandbox runs |

Sums over jobs overlap when jobs run at once, so they don't add up to the wall-clock.

## Policy events

- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured. This solver doesn't read them. Vora's `egress_denied` exists only in restricted mode, where it is a floor, and pools refuse that mode.

## Cost

- Wall-clock, what a rented GPU costs for this run: 0.636568 GPU-hours, 0.501297 EUR
- Time with a model request open, the lower bound: not measured
- Cost per task: not measured
- Price: 0.7875 EUR per hour
- Note: 1280 of 1888 completions came from the cache and were paid for by an earlier run
- Note: cost per task is not measured: dividing by every task would understate what a task costs
- Note: the lower bound is not measured: tasks overlapped, so their request times can't be added
