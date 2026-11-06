# Experiment 1 raw results

## Verdicts and outputs across arms

The 10000 candidates compared got the same verdict and outputs in every session that ran them.


## Leak tests

| Suite | Backend | Result | Passed | Failed | Skipped | Report | Vora build |
|---|---|---|---|---|---|---|---|
| Pool reset: `test_a_write_does_not_survive_into_the_next_run` | bwrap | passed | 3 | 0 | 0 | leak-bwrap.xml, written 2026-11-06 10:41 UTC | not in the report |
| No-reset control: `test_without_a_reset_the_same_write_does_survive` | bwrap | passed | 3 | 0 | 0 | leak-bwrap.xml, written 2026-11-06 10:41 UTC | not in the report |
| Vora: leak matrices and disconnect | bwrap | passed | 31 | 0 | 0 | vora-leak-bwrap.log, written 2026-11-06 10:42 UTC | 4260c8c1086fe338e01eccc2c67fc6577cfd65c4 |

## Arms

Wall-clock in ms, start to exit, over complete sessions. Ordinary programs are every class but memory_hungry, slow, timeout.

| Arm | Sessions | Runs, pooled | p50 | p90 | p99 | Max | Per session: p50 median (range) | p99 median (range) |
|---|---|---|---|---|---|---|---|---|
| cold | 5 | 9910 | 229.6 | 251.1 | 279.1 | 363.1 | 230.1 (227.9 to 231.0) | 278.3 (268.6 to 291.1) |
| warm | 5 | 9910 | 64.1 | 70.6 | 94.0 | 122.4 | 64.3 (63.4 to 64.5) | 97.2 (89.5 to 97.3) |
| warm-no-reset (UNSAFE: no reset between runs, an experimental control only) | 5 | 9910 | 63.2 | 71.9 | 91.4 | 113.5 | 63.2 (63.1 to 63.2) | 92.0 (87.7 to 94.2) |

All classes. The expensive ones are under 1% of the runs, so when they are the slowest they fill most of the slowest 1%, and this p99 is then a near-worst run.

| Arm | Sessions | Runs, pooled | p50 | p90 | p99 | Max | Per session: p50 median (range) | p99 median (range) |
|---|---|---|---|---|---|---|---|---|
| cold | 5 | 10000 | 229.7 | 252.0 | 350.1 | 2272.4 | 230.4 (228.0 to 231.1) | 350.1 (339.2 to 360.7) |
| warm | 5 | 10000 | 64.1 | 71.1 | 113.3 | 2096.0 | 64.3 (63.4 to 64.6) | 113.1 (106.1 to 115.1) |
| warm-no-reset (UNSAFE: no reset between runs, an experimental control only) | 5 | 10000 | 63.2 | 72.4 | 107.2 | 2096.9 | 63.2 (63.2 to 63.2) | 106.6 (105.5 to 107.2) |

| Arm | Reset p50, ms | Reset p99, ms | Resets reported | No figure from Vora | Reset failures | Programs/s (range) | Infrastructure failures | Off shape, against its bound | Hand-written not passed |
|---|---|---|---|---|---|---|---|---|---|
| cold | not measured | not measured | 0 | 10000 | 0 | 33.4 (33.4 to 33.5) | 0 of 10000 | 0, bound 0 | 0 |
| warm | 3.0 | 6.0 | 9920 | 80 | 0 | 104.6 (104.2 to 105.3) | 0 of 10000 | 0, bound 100 | 0 |
| warm-no-reset (UNSAFE: no reset between runs, an experimental control only) | not measured | not measured | 0 | 10000 | 0 | 111.3 (109.1 to 112.1) | 0 of 10000 | 0, bound 100 | 0 |

A session's p99 rests on its slowest 1%: about 20 runs of the 1982 ordinary runs in the smallest session here. Read the pooled p99 with the per-session range.
Session order: warm, warm-no-reset, cold, warm-no-reset, cold, warm, cold, warm, warm-no-reset, warm, warm-no-reset, cold, warm-no-reset, cold, warm.

## warm, session 6d3da2

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100}
- Corpus: seed 1, sha256 f8067a09337a, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 470 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 49 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 49 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 0.38 0.47 0.26 at the start, 2.81 1.02 0.45 at the end, client CPU in the measured window 7.0 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 778, 'crashed': 672, 'invalid': 330, 'passed': 218, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_OK': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 104.3, 2000 verdicts over 19.2 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 63.4 | 70.1 | 113.3 | 2061.5 |
| Startup (Vora) | 154 | 1846 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 2.9 | 4.9 | 35.9 | 64.3 |
| Execution (client) | 2000 | 0 | 60.1 | 64.3 | 89.3 | 2059.4 |
| This run's reset (Vora) | 1984 | 16 | 3.0 | 4.0 | 6.0 | 14.0 |
| Start to end of stream (client) | 2000 | 0 | 67.6 | 74.7 | 117.4 | 2067.3 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 63.4 | 69.3 | 97.2 | 121.0 | | |
| All classes | 2000 | 2000 | 0 | 63.4 | 70.1 | 113.3 | 2061.5 | 98.7% | {'failed': 778, 'crashed': 672, 'invalid': 330, 'passed': 218, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 63.1 | 67.9 | 89.6 | 109.4 | 9.0% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 63.2 | 69.1 | 92.6 | 121.0 | 45.0% | {'failed': 755, 'crashed': 132, 'invalid': 113, 'passed': 2} |
| syntax_error | 200 | 200 | 0 | 63.0 | 69.4 | 103.1 | 114.1 | 9.0% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 63.1 | 69.9 | 79.8 | 80.7 | 4.5% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 63.3 | 68.5 | 106.7 | 109.1 | 10.8% | {'invalid': 217, 'failed': 23} |
| crash | 240 | 240 | 0 | 64.6 | 72.7 | 94.0 | 99.8 | 11.0% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 861.8 | 1062.3 | 1267.1 | 1267.1 | 5.5% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 275.5 | 430.5 | 430.5 | 430.5 | 1.2% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2061.5 | 2061.5 | 2061.5 | 2061.5 | 2.7% | {'timeout': 2} |

## warm-no-reset (UNSAFE: no reset between runs, an experimental control only), session d6a9c4

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100, 'reuse': 'unsafe_no_reset'}
- Corpus: seed 1, sha256 f8067a09337a, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 470 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 49 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 49 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 2.81 1.02 0.45 at the start, 4.35 1.49 0.61 at the end, client CPU in the measured window 6.6 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 778, 'crashed': 672, 'invalid': 330, 'passed': 218, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_SKIPPED': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 109.3, 2000 verdicts over 18.3 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 63.2 | 71.7 | 107.2 | 2067.3 |
| Startup (Vora) | 167 | 1833 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 2.9 | 4.9 | 33.3 | 53.4 |
| Execution (client) | 2000 | 0 | 59.8 | 65.0 | 87.0 | 2064.1 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 63.9 | 72.5 | 108.2 | 2068.0 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 63.2 | 71.0 | 92.0 | 110.0 | | |
| All classes | 2000 | 2000 | 0 | 63.2 | 71.7 | 107.2 | 2067.3 | 98.5% | {'failed': 778, 'crashed': 672, 'invalid': 330, 'passed': 218, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 62.9 | 70.2 | 92.7 | 108.4 | 8.9% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 63.2 | 70.5 | 89.4 | 99.1 | 44.7% | {'failed': 755, 'crashed': 132, 'invalid': 113, 'passed': 2} |
| syntax_error | 200 | 200 | 0 | 63.2 | 70.8 | 88.2 | 110.0 | 8.9% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 63.1 | 71.3 | 84.1 | 93.3 | 4.4% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 62.7 | 71.7 | 95.2 | 102.2 | 10.7% | {'invalid': 217, 'failed': 23} |
| crash | 240 | 240 | 0 | 64.1 | 72.5 | 94.2 | 107.2 | 10.9% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 859.2 | 1065.5 | 1264.9 | 1264.9 | 5.7% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 284.4 | 434.1 | 434.1 | 434.1 | 1.3% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2066.2 | 2067.3 | 2067.3 | 2067.3 | 2.8% | {'timeout': 2} |

## cold, session 9b3dfa

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 0, 'max_size': 16}
- Corpus: seed 1, sha256 f8067a09337a, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 470 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 49 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 49 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.68 1.44 0.61 at the start, 6.09 2.50 1.02 at the end, client CPU in the measured window 7.1 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 778, 'crashed': 672, 'invalid': 330, 'passed': 218, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 0, cold 2000; not what this arm requires: 0 of 2000 (0.0%), against a bound of 0; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_RETIRED': 2000}
- Retired at check-in: {'shrink': 2000}. 2000 sandboxes, 2000 first runs, longest sandbox 1 runs
- Programs per second: 33.4, 2000 verdicts over 59.9 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 228.3 | 253.3 | 339.2 | 2272.4 |
| Startup (Vora) | 2000 | 0 | 170.0 | 194.0 | 229.0 | 273.0 |
| Startup (client) | 2000 | 0 | 173.7 | 197.3 | 232.6 | 282.1 |
| Execution (client) | 2000 | 0 | 54.6 | 60.0 | 71.8 | 2061.4 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 228.9 | 254.0 | 339.6 | 2273.6 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 228.1 | 251.9 | 291.1 | 349.6 | | |
| All classes | 2000 | 2000 | 0 | 228.3 | 253.3 | 339.2 | 2272.4 | 99.7% | {'failed': 778, 'crashed': 672, 'invalid': 330, 'passed': 218, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 227.0 | 249.1 | 277.7 | 313.3 | 9.6% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 227.8 | 252.7 | 299.3 | 349.6 | 48.6% | {'failed': 755, 'crashed': 132, 'invalid': 113, 'passed': 2} |
| syntax_error | 200 | 200 | 0 | 227.5 | 251.2 | 290.1 | 293.6 | 9.7% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 225.8 | 250.9 | 269.3 | 299.4 | 4.8% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 230.3 | 252.3 | 281.9 | 284.8 | 11.7% | {'invalid': 217, 'failed': 23} |
| crash | 240 | 240 | 0 | 229.3 | 252.1 | 283.1 | 298.4 | 11.7% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 1021.2 | 1241.1 | 1428.3 | 1428.3 | 2.1% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 420.0 | 570.3 | 570.3 | 570.3 | 0.6% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2239.7 | 2272.4 | 2272.4 | 2272.4 | 0.9% | {'timeout': 2} |

## warm-no-reset (UNSAFE: no reset between runs, an experimental control only), session 5a2053

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100, 'reuse': 'unsafe_no_reset'}
- Corpus: seed 2, sha256 c626b8540dc2, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 476 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 52 distinct), wrong_shape 240 (12.00%, 78 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.75 2.27 0.99 at the start, 5.11 2.68 1.15 at the end, client CPU in the measured window 6.6 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 781, 'invalid': 328, 'crashed': 666, 'passed': 223, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_SKIPPED': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 109.1, 2000 verdicts over 18.3 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 63.2 | 73.4 | 105.5 | 2063.6 |
| Startup (Vora) | 177 | 1823 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 2.9 | 5.1 | 27.7 | 53.4 |
| Execution (client) | 2000 | 0 | 59.7 | 66.6 | 93.1 | 2059.9 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 63.8 | 74.3 | 106.7 | 2064.2 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 63.1 | 73.1 | 92.2 | 113.5 | | |
| All classes | 2000 | 2000 | 0 | 63.2 | 73.4 | 105.5 | 2063.6 | 98.4% | {'failed': 781, 'invalid': 328, 'crashed': 666, 'passed': 223, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 63.3 | 75.4 | 95.8 | 102.6 | 9.0% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 62.9 | 72.5 | 100.1 | 113.5 | 44.7% | {'failed': 748, 'invalid': 121, 'crashed': 126, 'passed': 7} |
| syntax_error | 200 | 200 | 0 | 62.7 | 72.3 | 80.8 | 87.3 | 8.8% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 62.6 | 72.6 | 89.1 | 94.1 | 4.5% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 63.1 | 72.2 | 86.2 | 86.4 | 10.7% | {'failed': 33, 'invalid': 207} |
| crash | 240 | 240 | 0 | 64.5 | 73.4 | 82.5 | 85.6 | 10.9% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 865.8 | 1062.4 | 1070.6 | 1070.6 | 5.7% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 283.1 | 391.4 | 391.4 | 391.4 | 1.3% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2061.6 | 2063.6 | 2063.6 | 2063.6 | 2.8% | {'timeout': 2} |

## cold, session 73fafb

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 0, 'max_size': 16}
- Corpus: seed 2, sha256 c626b8540dc2, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 476 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 52 distinct), wrong_shape 240 (12.00%, 78 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.97 2.55 1.13 at the start, 6.87 3.68 1.62 at the end, client CPU in the measured window 7.1 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 781, 'invalid': 328, 'crashed': 666, 'passed': 223, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 0, cold 2000; not what this arm requires: 0 of 2000 (0.0%), against a bound of 0; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_RETIRED': 2000}
- Retired at check-in: {'shrink': 2000}. 2000 sandboxes, 2000 first runs, longest sandbox 1 runs
- Programs per second: 33.5, 2000 verdicts over 59.6 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 228.0 | 251.8 | 350.1 | 2229.0 |
| Startup (Vora) | 2000 | 0 | 170.0 | 192.0 | 213.0 | 274.0 |
| Startup (client) | 2000 | 0 | 173.5 | 195.3 | 216.3 | 283.9 |
| Execution (client) | 2000 | 0 | 54.8 | 60.3 | 71.3 | 2059.5 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 228.8 | 252.5 | 350.7 | 2229.4 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 227.9 | 250.7 | 272.5 | 352.2 | | |
| All classes | 2000 | 2000 | 0 | 228.0 | 251.8 | 350.1 | 2229.0 | 99.8% | {'failed': 781, 'invalid': 328, 'crashed': 666, 'passed': 223, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 226.4 | 249.9 | 271.8 | 282.8 | 9.6% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 228.4 | 250.8 | 270.6 | 352.2 | 48.6% | {'failed': 748, 'invalid': 121, 'crashed': 126, 'passed': 7} |
| syntax_error | 200 | 200 | 0 | 228.7 | 250.7 | 272.5 | 345.6 | 9.7% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 226.8 | 243.9 | 263.9 | 290.2 | 4.8% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 226.1 | 252.4 | 277.7 | 350.9 | 11.6% | {'failed': 33, 'invalid': 207} |
| crash | 240 | 240 | 0 | 228.0 | 251.7 | 270.1 | 350.1 | 11.7% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 1027.2 | 1233.3 | 1272.9 | 1272.9 | 2.1% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 426.8 | 535.6 | 535.6 | 535.6 | 0.6% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2222.1 | 2229.0 | 2229.0 | 2229.0 | 0.9% | {'timeout': 2} |

## warm, session 6893cf

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100}
- Corpus: seed 2, sha256 c626b8540dc2, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 476 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 52 distinct), wrong_shape 240 (12.00%, 78 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.65 3.25 1.56 at the start, 5.59 3.72 1.75 at the end, client CPU in the measured window 7.0 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 781, 'invalid': 328, 'crashed': 666, 'passed': 223, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_OK': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 104.2, 2000 verdicts over 19.2 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 63.6 | 70.9 | 112.9 | 2064.2 |
| Startup (Vora) | 159 | 1841 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 3.0 | 5.1 | 37.4 | 67.6 |
| Execution (client) | 2000 | 0 | 60.3 | 64.6 | 105.8 | 2060.9 |
| This run's reset (Vora) | 1984 | 16 | 3.0 | 4.0 | 6.0 | 14.0 |
| Start to end of stream (client) | 2000 | 0 | 67.8 | 75.0 | 116.0 | 2068.3 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 63.6 | 69.8 | 97.3 | 122.4 | | |
| All classes | 2000 | 2000 | 0 | 63.6 | 70.9 | 112.9 | 2064.2 | 98.9% | {'failed': 781, 'invalid': 328, 'crashed': 666, 'passed': 223, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 63.8 | 69.8 | 80.5 | 99.0 | 9.0% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 63.5 | 69.2 | 98.5 | 122.4 | 45.2% | {'invalid': 121, 'failed': 748, 'crashed': 126, 'passed': 7} |
| syntax_error | 200 | 200 | 0 | 63.0 | 69.3 | 91.8 | 103.6 | 8.9% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 63.4 | 70.8 | 83.5 | 96.6 | 4.5% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 63.5 | 69.2 | 102.9 | 109.1 | 10.9% | {'failed': 33, 'invalid': 207} |
| crash | 240 | 240 | 0 | 64.8 | 73.6 | 89.0 | 99.7 | 11.0% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 864.1 | 1066.1 | 1089.0 | 1089.0 | 5.5% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 274.4 | 389.3 | 389.3 | 389.3 | 1.2% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2063.6 | 2064.2 | 2064.2 | 2064.2 | 2.7% | {'timeout': 2} |

## cold, session c1b6c9

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 0, 'max_size': 16}
- Corpus: seed 3, sha256 11fa903e602b, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 473 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 49 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.81 3.45 1.71 at the start, 7.05 4.46 2.17 at the end, client CPU in the measured window 7.1 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'passed': 219, 'failed': 801, 'crashed': 651, 'invalid': 327, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 0, cold 2000; not what this arm requires: 0 of 2000 (0.0%), against a bound of 0; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_RETIRED': 2000}
- Retired at check-in: {'shrink': 2000}. 2000 sandboxes, 2000 first runs, longest sandbox 1 runs
- Programs per second: 33.4, 2000 verdicts over 59.9 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 231.1 | 251.7 | 350.8 | 2243.1 |
| Startup (Vora) | 2000 | 0 | 173.0 | 193.0 | 218.0 | 285.0 |
| Startup (client) | 2000 | 0 | 176.0 | 196.5 | 220.6 | 293.7 |
| Execution (client) | 2000 | 0 | 54.6 | 59.8 | 70.6 | 2053.4 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 231.7 | 252.4 | 351.6 | 2243.7 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 231.0 | 251.1 | 278.3 | 356.8 | | |
| All classes | 2000 | 2000 | 0 | 231.1 | 251.7 | 350.8 | 2243.1 | 99.7% | {'passed': 219, 'failed': 801, 'crashed': 651, 'invalid': 327, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 230.3 | 250.3 | 287.3 | 308.4 | 9.7% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 230.9 | 251.4 | 273.8 | 340.3 | 48.7% | {'failed': 774, 'invalid': 114, 'crashed': 111, 'passed': 3} |
| syntax_error | 200 | 200 | 0 | 231.2 | 248.3 | 275.8 | 342.9 | 9.7% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 229.6 | 251.8 | 304.9 | 350.8 | 4.9% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 231.1 | 250.3 | 279.6 | 354.1 | 11.7% | {'invalid': 213, 'failed': 27} |
| crash | 240 | 240 | 0 | 231.6 | 252.1 | 275.8 | 356.8 | 11.7% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 822.4 | 994.7 | 1015.0 | 1015.0 | 1.7% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 463.5 | 600.9 | 600.9 | 600.9 | 0.6% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2208.8 | 2243.1 | 2243.1 | 2243.1 | 0.9% | {'timeout': 2} |

## warm, session c79b98

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100}
- Corpus: seed 3, sha256 11fa903e602b, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 473 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 49 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.98 3.98 2.09 at the start, 5.38 4.31 2.24 at the end, client CPU in the measured window 7.1 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'passed': 219, 'failed': 801, 'crashed': 651, 'invalid': 327, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_OK': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 23 sandboxes, 15 first runs, longest sandbox 100 runs
- Programs per second: 105.2, 2000 verdicts over 19.0 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 64.3 | 71.4 | 113.1 | 2078.9 |
| Startup (Vora) | 148 | 1852 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 2.9 | 4.6 | 38.5 | 64.4 |
| Execution (client) | 2000 | 0 | 61.0 | 65.7 | 89.1 | 2071.7 |
| This run's reset (Vora) | 1984 | 16 | 3.0 | 4.0 | 6.0 | 16.0 |
| Start to end of stream (client) | 2000 | 0 | 68.6 | 76.4 | 118.1 | 2083.4 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 64.3 | 71.0 | 97.2 | 120.8 | | |
| All classes | 2000 | 2000 | 0 | 64.3 | 71.4 | 113.1 | 2078.9 | 99.5% | {'passed': 219, 'failed': 801, 'crashed': 651, 'invalid': 327, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 64.1 | 73.0 | 97.8 | 109.9 | 9.2% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 64.2 | 70.4 | 90.9 | 120.8 | 45.9% | {'failed': 774, 'invalid': 114, 'crashed': 111, 'passed': 3} |
| syntax_error | 200 | 200 | 0 | 64.3 | 71.8 | 100.6 | 107.7 | 9.2% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 63.6 | 69.9 | 89.5 | 112.2 | 4.6% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 63.9 | 70.4 | 106.0 | 114.2 | 11.0% | {'invalid': 213, 'failed': 27} |
| crash | 240 | 240 | 0 | 65.5 | 73.5 | 96.2 | 112.9 | 11.3% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 662.0 | 814.0 | 867.6 | 867.6 | 4.2% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 326.0 | 431.1 | 431.1 | 431.1 | 1.3% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2074.6 | 2078.9 | 2078.9 | 2078.9 | 2.7% | {'timeout': 2} |

## warm-no-reset (UNSAFE: no reset between runs, an experimental control only), session 4b465d

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100, 'reuse': 'unsafe_no_reset'}
- Corpus: seed 3, sha256 11fa903e602b, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 473 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 49 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.85 4.03 2.19 at the start, 4.60 4.17 2.28 at the end, client CPU in the measured window 6.6 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 801, 'passed': 219, 'crashed': 651, 'invalid': 327, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_SKIPPED': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 112.1, 2000 verdicts over 17.8 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 63.2 | 71.4 | 106.6 | 2063.2 |
| Startup (Vora) | 183 | 1817 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 2.9 | 5.3 | 30.9 | 61.0 |
| Execution (client) | 2000 | 0 | 59.6 | 65.5 | 80.0 | 2060.4 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 63.8 | 72.4 | 108.1 | 2064.1 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 63.1 | 70.9 | 91.3 | 112.8 | | |
| All classes | 2000 | 2000 | 0 | 63.2 | 71.4 | 106.6 | 2063.2 | 99.5% | {'failed': 801, 'passed': 219, 'crashed': 651, 'invalid': 327, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 62.9 | 70.6 | 79.1 | 89.7 | 9.1% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 62.9 | 70.5 | 85.9 | 112.8 | 45.7% | {'failed': 774, 'invalid': 114, 'crashed': 111, 'passed': 3} |
| syntax_error | 200 | 200 | 0 | 62.7 | 71.6 | 83.3 | 89.3 | 9.1% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 63.4 | 71.5 | 92.7 | 106.6 | 4.6% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 63.2 | 71.3 | 100.6 | 104.8 | 11.0% | {'invalid': 213, 'failed': 27} |
| crash | 240 | 240 | 0 | 64.6 | 71.0 | 91.3 | 102.3 | 11.2% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 663.2 | 814.9 | 867.9 | 867.9 | 4.5% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 325.3 | 433.8 | 433.8 | 433.8 | 1.4% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2062.1 | 2063.2 | 2063.2 | 2063.2 | 2.9% | {'timeout': 2} |

## warm, session 88bfca

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100}
- Corpus: seed 4, sha256 5bcc15e3b378, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 492 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 53 distinct), wrong_shape 240 (12.00%, 76 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.89 4.04 2.26 at the start, 5.25 4.33 2.39 at the end, client CPU in the measured window 7.1 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'crashed': 649, 'failed': 791, 'passed': 224, 'invalid': 334, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_OK': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 104.6, 2000 verdicts over 19.1 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 64.5 | 71.5 | 106.1 | 2096.0 |
| Startup (Vora) | 166 | 1834 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 3.0 | 4.9 | 31.5 | 54.9 |
| Execution (client) | 2000 | 0 | 61.0 | 65.6 | 76.6 | 2062.8 |
| This run's reset (Vora) | 1984 | 16 | 3.0 | 4.0 | 6.0 | 13.0 |
| Start to end of stream (client) | 2000 | 0 | 68.7 | 76.4 | 110.3 | 2101.1 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 64.5 | 71.0 | 89.5 | 111.5 | | |
| All classes | 2000 | 2000 | 0 | 64.5 | 71.5 | 106.1 | 2096.0 | 99.5% | {'crashed': 649, 'failed': 791, 'passed': 224, 'invalid': 334, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 64.4 | 71.7 | 89.5 | 99.7 | 9.2% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 64.2 | 70.6 | 87.4 | 107.6 | 45.7% | {'failed': 766, 'invalid': 119, 'crashed': 109, 'passed': 8} |
| syntax_error | 200 | 200 | 0 | 64.1 | 70.7 | 86.6 | 95.5 | 9.1% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 64.5 | 71.1 | 83.3 | 94.3 | 4.6% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 64.3 | 70.5 | 86.7 | 91.6 | 10.9% | {'invalid': 215, 'failed': 25} |
| crash | 240 | 240 | 0 | 65.4 | 71.9 | 89.5 | 111.5 | 11.1% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 666.9 | 1061.8 | 1063.5 | 1063.5 | 4.8% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 281.3 | 449.2 | 449.2 | 449.2 | 1.3% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2064.9 | 2096.0 | 2096.0 | 2096.0 | 2.7% | {'timeout': 2} |

## warm-no-reset (UNSAFE: no reset between runs, an experimental control only), session a8ed5e

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100, 'reuse': 'unsafe_no_reset'}
- Corpus: seed 4, sha256 5bcc15e3b378, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 492 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 53 distinct), wrong_shape 240 (12.00%, 76 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.67 4.03 2.34 at the start, 5.14 4.34 2.47 at the end, client CPU in the measured window 6.6 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'crashed': 649, 'failed': 791, 'invalid': 334, 'passed': 224, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_SKIPPED': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 111.3, 2000 verdicts over 18.0 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 63.2 | 72.5 | 107.1 | 2096.9 |
| Startup (Vora) | 162 | 1838 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 2.9 | 4.9 | 29.4 | 57.0 |
| Execution (client) | 2000 | 0 | 59.7 | 65.5 | 82.1 | 2060.2 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 63.9 | 73.3 | 108.5 | 2097.5 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 63.2 | 71.9 | 87.7 | 109.6 | | |
| All classes | 2000 | 2000 | 0 | 63.2 | 72.5 | 107.1 | 2096.9 | 99.5% | {'crashed': 649, 'failed': 791, 'invalid': 334, 'passed': 224, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 63.2 | 72.7 | 93.5 | 105.2 | 9.2% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 63.0 | 71.3 | 85.6 | 109.6 | 45.4% | {'failed': 766, 'invalid': 119, 'crashed': 109, 'passed': 8} |
| syntax_error | 200 | 200 | 0 | 63.2 | 74.4 | 87.0 | 94.3 | 9.1% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 63.0 | 71.2 | 98.6 | 107.1 | 4.6% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 62.9 | 70.9 | 82.0 | 85.8 | 10.8% | {'invalid': 215, 'failed': 25} |
| crash | 240 | 240 | 0 | 64.5 | 72.3 | 94.1 | 108.2 | 11.1% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 664.9 | 1063.6 | 1063.8 | 1063.8 | 5.1% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 290.9 | 432.3 | 432.3 | 432.3 | 1.3% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2062.8 | 2096.9 | 2096.9 | 2096.9 | 2.9% | {'timeout': 2} |

## cold, session a25801

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 0, 'max_size': 16}
- Corpus: seed 4, sha256 5bcc15e3b378, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 492 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 53 distinct), wrong_shape 240 (12.00%, 76 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.76 4.07 2.42 at the start, 7.17 5.00 2.85 at the end, client CPU in the measured window 7.2 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'crashed': 649, 'failed': 791, 'invalid': 334, 'passed': 224, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 0, cold 2000; not what this arm requires: 0 of 2000 (0.0%), against a bound of 0; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_RETIRED': 2000}
- Retired at check-in: {'shrink': 2000}. 2000 sandboxes, 2000 first runs, longest sandbox 1 runs
- Programs per second: 33.4, 2000 verdicts over 59.9 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 230.6 | 250.7 | 345.0 | 2219.3 |
| Startup (Vora) | 2000 | 0 | 172.0 | 191.0 | 210.0 | 278.0 |
| Startup (client) | 2000 | 0 | 175.9 | 194.4 | 213.6 | 286.2 |
| Execution (client) | 2000 | 0 | 54.7 | 60.1 | 70.1 | 2056.2 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 231.2 | 251.3 | 345.6 | 2219.9 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 230.3 | 249.8 | 268.6 | 347.6 | | |
| All classes | 2000 | 2000 | 0 | 230.6 | 250.7 | 345.0 | 2219.3 | 99.7% | {'crashed': 649, 'failed': 791, 'invalid': 334, 'passed': 224, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 231.3 | 250.1 | 262.2 | 345.0 | 9.7% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 230.1 | 249.7 | 265.2 | 334.2 | 48.7% | {'failed': 766, 'invalid': 119, 'crashed': 109, 'passed': 8} |
| syntax_error | 200 | 200 | 0 | 230.7 | 246.0 | 271.8 | 305.2 | 9.7% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 229.7 | 252.6 | 266.3 | 271.6 | 4.9% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 229.5 | 248.7 | 280.6 | 346.3 | 11.7% | {'invalid': 215, 'failed': 25} |
| crash | 240 | 240 | 0 | 231.5 | 251.6 | 274.2 | 347.6 | 11.7% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 839.2 | 1224.4 | 1237.3 | 1237.3 | 1.9% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 457.0 | 562.9 | 562.9 | 562.9 | 0.6% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2214.6 | 2219.3 | 2219.3 | 2219.3 | 0.9% | {'timeout': 2} |

## warm-no-reset (UNSAFE: no reset between runs, an experimental control only), session d06000

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100, 'reuse': 'unsafe_no_reset'}
- Corpus: seed 5, sha256 a19a31fb3b47, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 465 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 51 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.94 4.45 2.75 at the start, 5.30 4.73 2.88 at the end, client CPU in the measured window 6.7 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'passed': 217, 'invalid': 349, 'crashed': 661, 'failed': 771, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_SKIPPED': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 112.1, 2000 verdicts over 17.8 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 63.2 | 72.5 | 106.2 | 2064.4 |
| Startup (Vora) | 171 | 1829 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 3.0 | 5.3 | 32.7 | 52.1 |
| Execution (client) | 2000 | 0 | 59.7 | 65.7 | 82.3 | 2061.9 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 63.9 | 73.6 | 107.6 | 2065.0 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 63.2 | 72.1 | 94.2 | 107.8 | | |
| All classes | 2000 | 2000 | 0 | 63.2 | 72.5 | 106.2 | 2064.4 | 99.5% | {'passed': 217, 'invalid': 349, 'crashed': 661, 'failed': 771, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 62.5 | 69.6 | 87.5 | 93.1 | 9.1% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 63.2 | 72.3 | 96.3 | 107.8 | 46.2% | {'invalid': 130, 'failed': 750, 'crashed': 121, 'passed': 1} |
| syntax_error | 200 | 200 | 0 | 62.6 | 74.2 | 91.0 | 106.2 | 9.1% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 62.5 | 70.7 | 76.1 | 86.7 | 4.5% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 63.5 | 71.7 | 87.7 | 102.6 | 11.0% | {'invalid': 219, 'failed': 21} |
| crash | 240 | 240 | 0 | 64.0 | 73.0 | 91.4 | 98.0 | 11.2% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 561.9 | 814.5 | 820.6 | 820.6 | 4.2% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 311.9 | 436.9 | 436.9 | 436.9 | 1.3% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2063.6 | 2064.4 | 2064.4 | 2064.4 | 2.9% | {'timeout': 2} |

## cold, session 9c0251

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 0, 'max_size': 16}
- Corpus: seed 5, sha256 a19a31fb3b47, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 465 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 51 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.79 4.42 2.82 at the start, 6.52 5.07 3.14 at the end, client CPU in the measured window 7.1 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'invalid': 349, 'crashed': 661, 'passed': 217, 'failed': 771, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 0, cold 2000; not what this arm requires: 0 of 2000 (0.0%), against a bound of 0; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_RETIRED': 2000}
- Retired at check-in: {'shrink': 2000}. 2000 sandboxes, 2000 first runs, longest sandbox 1 runs
- Programs per second: 33.4, 2000 verdicts over 59.8 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 230.4 | 253.7 | 360.7 | 2227.7 |
| Startup (Vora) | 2000 | 0 | 172.0 | 195.0 | 218.0 | 292.0 |
| Startup (client) | 2000 | 0 | 175.2 | 198.1 | 221.3 | 299.3 |
| Execution (client) | 2000 | 0 | 55.0 | 60.3 | 72.6 | 2058.3 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 231.1 | 254.4 | 361.2 | 2228.4 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 230.1 | 252.6 | 280.1 | 363.1 | | |
| All classes | 2000 | 2000 | 0 | 230.4 | 253.7 | 360.7 | 2227.7 | 99.8% | {'invalid': 349, 'crashed': 661, 'passed': 217, 'failed': 771, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 230.5 | 253.5 | 282.6 | 363.1 | 9.8% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 229.5 | 252.0 | 278.6 | 362.3 | 48.8% | {'invalid': 130, 'failed': 750, 'crashed': 121, 'passed': 1} |
| syntax_error | 200 | 200 | 0 | 229.7 | 252.8 | 275.9 | 287.6 | 9.7% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 232.6 | 251.9 | 267.0 | 313.4 | 4.9% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 230.5 | 249.9 | 274.5 | 281.4 | 11.7% | {'invalid': 219, 'failed': 21} |
| crash | 240 | 240 | 0 | 231.4 | 255.5 | 282.7 | 353.4 | 11.7% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 724.8 | 969.8 | 1000.4 | 1000.4 | 1.6% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 465.5 | 591.9 | 591.9 | 591.9 | 0.6% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2222.7 | 2227.7 | 2227.7 | 2227.7 | 0.9% | {'timeout': 2} |

## warm, session 4db098

- Profile python-arc-bwrap, backend bwrap, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100}
- Corpus: seed 5, sha256 a19a31fb3b47, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 465 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 51 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 4.91 4.77 3.11 at the start, 5.86 5.00 3.22 at the end, client CPU in the measured window 7.1 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'invalid': 349, 'passed': 217, 'crashed': 661, 'failed': 771, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_OK': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 105.3, 2000 verdicts over 19.0 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode
- **Warning: this machine was busy at the start: load 4.91357421875 on 16 CPUs**

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 64.6 | 71.7 | 115.1 | 2070.8 |
| Startup (Vora) | 170 | 1830 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 3.0 | 5.2 | 30.8 | 68.5 |
| Execution (client) | 2000 | 0 | 61.0 | 66.0 | 89.0 | 2067.0 |
| This run's reset (Vora) | 1984 | 16 | 3.0 | 4.0 | 5.0 | 11.0 |
| Start to end of stream (client) | 2000 | 0 | 68.7 | 76.4 | 118.9 | 2076.7 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 64.5 | 71.0 | 92.5 | 122.2 | | |
| All classes | 2000 | 2000 | 0 | 64.6 | 71.7 | 115.1 | 2070.8 | 99.5% | {'invalid': 349, 'passed': 217, 'crashed': 661, 'failed': 771, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 64.2 | 70.3 | 88.8 | 95.4 | 9.2% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 64.4 | 71.0 | 92.5 | 122.2 | 46.2% | {'invalid': 130, 'failed': 750, 'crashed': 121, 'passed': 1} |
| syntax_error | 200 | 200 | 0 | 64.5 | 70.6 | 92.7 | 111.0 | 9.2% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 64.1 | 70.7 | 79.4 | 93.5 | 4.6% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 65.0 | 71.0 | 90.6 | 101.5 | 11.1% | {'invalid': 219, 'failed': 21} |
| crash | 240 | 240 | 0 | 65.3 | 71.5 | 93.2 | 103.4 | 11.2% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 563.1 | 812.5 | 817.1 | 817.1 | 4.0% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 323.3 | 442.9 | 442.9 | 442.9 | 1.3% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2065.5 | 2070.8 | 2070.8 | 2070.8 | 2.7% | {'timeout': 2} |

