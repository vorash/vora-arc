# Experiment 1 raw results

## Verdicts and outputs across arms

The 10000 candidates compared got the same verdict and outputs in every session that ran them.


## Leak tests

| Suite | Backend | Result | Passed | Failed | Skipped | Report | Vora build |
|---|---|---|---|---|---|---|---|
| Pool reset: `test_a_write_does_not_survive_into_the_next_run` | gvisor | passed | 3 | 0 | 0 | leak-gvisor.xml, written 2026-11-06 10:41 UTC | not in the report |
| No-reset control: `test_without_a_reset_the_same_write_does_survive` | gvisor | passed | 3 | 0 | 0 | leak-gvisor.xml, written 2026-11-06 10:41 UTC | not in the report |
| Vora: leak matrices and disconnect | gvisor | passed | 47 | 0 | 0 | vora-leak-gvisor.log, written 2026-11-06 10:47 UTC | 4260c8c1086fe338e01eccc2c67fc6577cfd65c4 |

## Arms

Wall-clock in ms, start to exit, over complete sessions. Ordinary programs are every class but memory_hungry, slow, timeout.

| Arm | Sessions | Runs, pooled | p50 | p90 | p99 | Max | Per session: p50 median (range) | p99 median (range) |
|---|---|---|---|---|---|---|---|---|
| cold | 5 | 9910 | 317.8 | 341.6 | 368.9 | 420.8 | 317.9 (317.2 to 318.3) | 370.0 (365.4 to 371.5) |
| warm | 5 | 9910 | 122.3 | 141.0 | 196.2 | 276.9 | 122.3 (121.9 to 122.8) | 196.2 (191.3 to 200.1) |
| warm-no-reset (UNSAFE: no reset between runs, an experimental control only) | 5 | 9910 | 123.7 | 147.9 | 187.4 | 288.9 | 123.6 (122.6 to 124.4) | 188.3 (181.4 to 194.1) |

All classes. The expensive ones are under 1% of the runs, so when they are the slowest they fill most of the slowest 1%, and this p99 is then a near-worst run.

| Arm | Sessions | Runs, pooled | p50 | p90 | p99 | Max | Per session: p50 median (range) | p99 median (range) |
|---|---|---|---|---|---|---|---|---|
| cold | 5 | 10000 | 318.0 | 342.6 | 383.4 | 2343.4 | 318.1 (317.3 to 318.5) | 382.3 (378.2 to 386.4) |
| warm | 5 | 10000 | 122.4 | 141.6 | 260.9 | 2133.0 | 122.4 (122.0 to 122.9) | 244.9 (228.4 to 269.8) |
| warm-no-reset (UNSAFE: no reset between runs, an experimental control only) | 5 | 10000 | 123.8 | 148.7 | 230.7 | 2142.3 | 123.8 (122.8 to 124.6) | 223.9 (219.0 to 279.1) |

| Arm | Reset p50, ms | Reset p99, ms | Resets reported | No figure from Vora | Reset failures | Programs/s (range) | Infrastructure failures | Off shape, against its bound | Hand-written not passed |
|---|---|---|---|---|---|---|---|---|---|
| cold | not measured | not measured | 0 | 10000 | 0 | 24.3 (24.3 to 24.4) | 0 of 10000 | 0, bound 0 | 0 |
| warm | 46.0 | 56.0 | 9920 | 80 | 0 | 44.1 (43.8 to 44.3) | 0 of 10000 | 0, bound 100 | 0 |
| warm-no-reset (UNSAFE: no reset between runs, an experimental control only) | not measured | not measured | 0 | 10000 | 0 | 58.3 (57.7 to 58.4) | 0 of 10000 | 0, bound 100 | 0 |

A session's p99 rests on its slowest 1%: about 20 runs of the 1982 ordinary runs in the smallest session here. Read the pooled p99 with the per-session range.
Session order: warm, warm-no-reset, cold, warm-no-reset, cold, warm, cold, warm, warm-no-reset, warm, warm-no-reset, cold, warm-no-reset, cold, warm.

## warm, session 7ba5b3

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100}
- Corpus: seed 1, sha256 f8067a09337a, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 470 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 49 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 49 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 2.82 4.30 3.07 at the start, 6.73 5.16 3.43 at the end, client CPU in the measured window 8.4 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 778, 'crashed': 672, 'invalid': 330, 'passed': 218, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_OK': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 44.0, 2000 verdicts over 45.5 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 122.4 | 141.1 | 241.4 | 2118.6 |
| Startup (Vora) | 105 | 1895 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 15.4 | 18.2 | 75.4 | 151.2 |
| Execution (client) | 2000 | 0 | 106.4 | 123.1 | 137.6 | 2103.1 |
| This run's reset (Vora) | 1984 | 16 | 46.0 | 50.0 | 55.0 | 62.0 |
| Start to end of stream (client) | 2000 | 0 | 170.2 | 188.5 | 288.4 | 2166.3 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 122.3 | 140.5 | 199.0 | 272.9 | | |
| All classes | 2000 | 2000 | 0 | 122.4 | 141.1 | 241.4 | 2118.6 | 99.7% | {'failed': 778, 'crashed': 672, 'invalid': 330, 'passed': 218, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 122.2 | 139.3 | 170.9 | 181.2 | 9.5% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 122.6 | 140.5 | 198.1 | 241.4 | 47.7% | {'failed': 755, 'crashed': 132, 'invalid': 113, 'passed': 2} |
| syntax_error | 200 | 200 | 0 | 121.1 | 140.2 | 233.3 | 272.9 | 9.5% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 119.4 | 137.1 | 168.9 | 199.4 | 4.7% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 119.7 | 137.4 | 201.0 | 238.9 | 11.3% | {'invalid': 217, 'failed': 23} |
| crash | 240 | 240 | 0 | 125.5 | 143.1 | 179.9 | 222.4 | 11.6% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 916.7 | 1128.0 | 1314.8 | 1314.8 | 2.6% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 775.6 | 1254.1 | 1254.1 | 1254.1 | 1.5% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2113.8 | 2118.6 | 2118.6 | 2118.6 | 1.2% | {'timeout': 2} |

## warm-no-reset (UNSAFE: no reset between runs, an experimental control only), session 610299

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100, 'reuse': 'unsafe_no_reset'}
- Corpus: seed 1, sha256 f8067a09337a, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 470 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 49 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 49 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.75 4.59 3.30 at the start, 5.88 5.02 3.50 at the end, client CPU in the measured window 7.7 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 778, 'crashed': 672, 'invalid': 330, 'passed': 218, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_SKIPPED': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 57.7, 2000 verdicts over 34.6 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 124.6 | 149.4 | 222.0 | 2119.8 |
| Startup (Vora) | 132 | 1868 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 15.7 | 20.2 | 70.3 | 117.0 |
| Execution (client) | 2000 | 0 | 108.5 | 131.5 | 149.9 | 2103.1 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 125.2 | 150.3 | 222.8 | 2120.5 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 124.4 | 148.9 | 188.3 | 234.7 | | |
| All classes | 2000 | 2000 | 0 | 124.6 | 149.4 | 222.0 | 2119.8 | 99.7% | {'failed': 778, 'crashed': 672, 'invalid': 330, 'passed': 218, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 125.6 | 149.0 | 188.3 | 211.7 | 9.4% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 124.4 | 149.2 | 189.8 | 234.7 | 47.1% | {'failed': 755, 'crashed': 132, 'invalid': 113, 'passed': 2} |
| syntax_error | 200 | 200 | 0 | 126.1 | 148.9 | 179.9 | 222.0 | 9.4% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 121.2 | 145.5 | 163.2 | 174.1 | 4.6% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 124.8 | 148.5 | 179.7 | 189.1 | 11.2% | {'invalid': 217, 'failed': 23} |
| crash | 240 | 240 | 0 | 123.9 | 147.3 | 187.1 | 219.5 | 11.3% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 925.4 | 1169.5 | 1326.5 | 1326.5 | 3.3% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 770.5 | 1206.0 | 1206.0 | 1206.0 | 1.9% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2113.5 | 2119.8 | 2119.8 | 2119.8 | 1.5% | {'timeout': 2} |

## cold, session b185e2

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 0, 'max_size': 16}
- Corpus: seed 1, sha256 f8067a09337a, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 470 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 49 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 49 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.88 4.61 3.40 at the start, 12.35 7.32 4.47 at the end, client CPU in the measured window 9.1 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 778, 'invalid': 330, 'crashed': 672, 'passed': 218, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 0, cold 2000; not what this arm requires: 0 of 2000 (0.0%), against a bound of 0; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_RETIRED': 2000}
- Retired at check-in: {'shrink': 2000}. 2000 sandboxes, 2000 first runs, longest sandbox 1 runs
- Programs per second: 24.3, 2000 verdicts over 82.2 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 318.4 | 341.5 | 378.2 | 2324.5 |
| Startup (Vora) | 2000 | 0 | 149.0 | 177.0 | 204.0 | 232.0 |
| Startup (client) | 2000 | 0 | 170.6 | 196.1 | 221.1 | 251.8 |
| Execution (client) | 2000 | 0 | 146.5 | 161.0 | 179.7 | 2134.8 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 319.3 | 342.3 | 379.0 | 2325.2 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 318.3 | 340.6 | 365.4 | 406.4 | | |
| All classes | 2000 | 2000 | 0 | 318.4 | 341.5 | 378.2 | 2324.5 | 99.8% | {'failed': 778, 'invalid': 330, 'crashed': 672, 'passed': 218, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 319.5 | 337.3 | 364.4 | 366.5 | 9.8% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 318.0 | 340.5 | 368.9 | 406.4 | 48.7% | {'failed': 755, 'crashed': 132, 'invalid': 113, 'passed': 2} |
| syntax_error | 200 | 200 | 0 | 317.9 | 343.9 | 359.9 | 373.5 | 9.7% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 316.2 | 338.9 | 361.8 | 364.2 | 4.8% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 317.5 | 338.8 | 368.0 | 386.7 | 11.7% | {'invalid': 217, 'failed': 23} |
| crash | 240 | 240 | 0 | 320.7 | 341.3 | 364.2 | 366.8 | 11.7% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 1117.2 | 1324.8 | 1512.1 | 1512.1 | 1.7% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 983.2 | 1485.7 | 1485.7 | 1485.7 | 1.0% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2308.0 | 2324.5 | 2324.5 | 2324.5 | 0.7% | {'timeout': 2} |

## warm-no-reset (UNSAFE: no reset between runs, an experimental control only), session 708675

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100, 'reuse': 'unsafe_no_reset'}
- Corpus: seed 2, sha256 c626b8540dc2, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 476 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 52 distinct), wrong_shape 240 (12.00%, 78 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 4.00 5.83 4.16 at the start, 6.72 6.30 4.38 at the end, client CPU in the measured window 7.6 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'crashed': 666, 'failed': 781, 'invalid': 328, 'passed': 223, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_SKIPPED': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 58.3, 2000 verdicts over 34.3 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 122.8 | 147.5 | 223.9 | 2119.7 |
| Startup (Vora) | 135 | 1865 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 15.6 | 20.4 | 67.1 | 114.5 |
| Execution (client) | 2000 | 0 | 107.0 | 129.2 | 144.3 | 2105.8 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 123.5 | 148.3 | 224.5 | 2120.4 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 122.6 | 146.7 | 181.4 | 230.7 | | |
| All classes | 2000 | 2000 | 0 | 122.8 | 147.5 | 223.9 | 2119.7 | 99.7% | {'crashed': 666, 'failed': 781, 'invalid': 328, 'passed': 223, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 121.9 | 145.6 | 174.6 | 196.5 | 9.3% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 122.9 | 146.8 | 180.7 | 230.7 | 47.0% | {'failed': 748, 'invalid': 121, 'crashed': 126, 'passed': 7} |
| syntax_error | 200 | 200 | 0 | 120.8 | 145.0 | 171.8 | 223.9 | 9.3% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 125.9 | 151.0 | 181.7 | 184.1 | 4.8% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 122.4 | 145.9 | 180.9 | 203.6 | 11.2% | {'failed': 33, 'invalid': 207} |
| crash | 240 | 240 | 0 | 123.5 | 146.7 | 181.4 | 230.7 | 11.4% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 929.1 | 1115.2 | 1123.2 | 1123.2 | 3.3% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 749.5 | 1069.3 | 1069.3 | 1069.3 | 1.9% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2109.0 | 2119.7 | 2119.7 | 2119.7 | 1.5% | {'timeout': 2} |

## cold, session 25d0b7

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 0, 'max_size': 16}
- Corpus: seed 2, sha256 c626b8540dc2, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 476 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 52 distinct), wrong_shape 240 (12.00%, 78 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.75 5.60 4.22 at the start, 14.72 8.82 5.48 at the end, client CPU in the measured window 9.0 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 781, 'invalid': 328, 'crashed': 666, 'passed': 223, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 0, cold 2000; not what this arm requires: 0 of 2000 (0.0%), against a bound of 0; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_RETIRED': 2000}
- Retired at check-in: {'shrink': 2000}. 2000 sandboxes, 2000 first runs, longest sandbox 1 runs
- Programs per second: 24.3, 2000 verdicts over 82.1 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 317.3 | 342.3 | 382.3 | 2310.0 |
| Startup (Vora) | 2000 | 0 | 150.0 | 179.0 | 201.0 | 239.0 |
| Startup (client) | 2000 | 0 | 170.9 | 197.3 | 221.6 | 261.9 |
| Execution (client) | 2000 | 0 | 145.3 | 161.5 | 186.7 | 2155.6 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 318.2 | 343.1 | 383.1 | 2310.7 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 317.2 | 341.7 | 367.0 | 389.8 | | |
| All classes | 2000 | 2000 | 0 | 317.3 | 342.3 | 382.3 | 2310.0 | 99.8% | {'failed': 781, 'invalid': 328, 'crashed': 666, 'passed': 223, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 318.5 | 337.8 | 367.1 | 383.0 | 9.7% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 317.0 | 342.1 | 366.0 | 389.8 | 48.7% | {'failed': 748, 'invalid': 121, 'crashed': 126, 'passed': 7} |
| syntax_error | 200 | 200 | 0 | 318.0 | 341.9 | 366.5 | 369.0 | 9.7% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 315.6 | 336.8 | 359.2 | 374.6 | 4.8% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 316.9 | 339.0 | 362.4 | 382.3 | 11.6% | {'failed': 33, 'invalid': 207} |
| crash | 240 | 240 | 0 | 316.4 | 342.3 | 370.3 | 379.6 | 11.7% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 1118.8 | 1319.8 | 1328.3 | 1328.3 | 1.7% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 974.7 | 1297.8 | 1297.8 | 1297.8 | 1.0% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2294.6 | 2310.0 | 2310.0 | 2310.0 | 0.7% | {'timeout': 2} |

## warm, session c1b865

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100}
- Corpus: seed 2, sha256 c626b8540dc2, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 476 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 52 distinct), wrong_shape 240 (12.00%, 78 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.89 6.76 5.03 at the start, 7.42 7.30 5.30 at the end, client CPU in the measured window 8.5 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'invalid': 328, 'failed': 781, 'crashed': 666, 'passed': 223, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_OK': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 43.8, 2000 verdicts over 45.6 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 122.9 | 142.0 | 260.9 | 2122.0 |
| Startup (Vora) | 117 | 1883 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 15.5 | 18.4 | 65.1 | 147.6 |
| Execution (client) | 2000 | 0 | 106.9 | 124.0 | 138.8 | 2105.0 |
| This run's reset (Vora) | 1984 | 16 | 46.0 | 50.0 | 57.0 | 67.0 |
| Start to end of stream (client) | 2000 | 0 | 170.9 | 190.3 | 305.1 | 2168.7 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 122.8 | 141.6 | 191.3 | 268.4 | | |
| All classes | 2000 | 2000 | 0 | 122.9 | 142.0 | 260.9 | 2122.0 | 99.7% | {'invalid': 328, 'failed': 781, 'crashed': 666, 'passed': 223, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 123.7 | 142.7 | 168.8 | 268.4 | 9.5% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 122.4 | 141.6 | 187.9 | 236.3 | 47.8% | {'invalid': 121, 'failed': 748, 'crashed': 126, 'passed': 7} |
| syntax_error | 200 | 200 | 0 | 122.2 | 139.1 | 155.1 | 260.9 | 9.4% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 123.7 | 142.2 | 191.3 | 222.1 | 4.8% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 122.9 | 141.7 | 174.5 | 263.3 | 11.4% | {'invalid': 207, 'failed': 33} |
| crash | 240 | 240 | 0 | 123.1 | 141.7 | 201.3 | 237.8 | 11.5% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 920.8 | 1116.6 | 1122.3 | 1122.3 | 2.6% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 742.6 | 1085.0 | 1085.0 | 1085.0 | 1.5% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2115.3 | 2122.0 | 2122.0 | 2122.0 | 1.2% | {'timeout': 2} |

## cold, session ba795c

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 0, 'max_size': 16}
- Corpus: seed 3, sha256 11fa903e602b, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 473 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 49 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.90 6.41 5.09 at the start, 15.06 9.32 6.22 at the end, client CPU in the measured window 9.0 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'crashed': 651, 'passed': 219, 'failed': 801, 'invalid': 327, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 0, cold 2000; not what this arm requires: 0 of 2000 (0.0%), against a bound of 0; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_RETIRED': 2000}
- Retired at check-in: {'shrink': 2000}. 2000 sandboxes, 2000 first runs, longest sandbox 1 runs
- Programs per second: 24.3, 2000 verdicts over 82.2 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 318.5 | 344.1 | 381.2 | 2343.4 |
| Startup (Vora) | 2000 | 0 | 152.0 | 179.0 | 204.0 | 235.0 |
| Startup (client) | 2000 | 0 | 172.2 | 198.5 | 223.8 | 250.9 |
| Execution (client) | 2000 | 0 | 145.2 | 161.1 | 181.3 | 2137.7 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 319.4 | 345.1 | 381.9 | 2344.1 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 318.3 | 343.1 | 370.0 | 391.6 | | |
| All classes | 2000 | 2000 | 0 | 318.5 | 344.1 | 381.2 | 2343.4 | 99.8% | {'crashed': 651, 'passed': 219, 'failed': 801, 'invalid': 327, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 318.5 | 342.7 | 367.5 | 381.2 | 9.8% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 317.8 | 342.1 | 367.1 | 379.7 | 48.7% | {'failed': 774, 'invalid': 114, 'crashed': 111, 'passed': 3} |
| syntax_error | 200 | 200 | 0 | 319.2 | 342.4 | 372.8 | 383.2 | 9.8% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 317.7 | 348.4 | 372.4 | 391.6 | 4.9% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 319.1 | 343.5 | 369.2 | 377.7 | 11.8% | {'invalid': 213, 'failed': 27} |
| crash | 240 | 240 | 0 | 319.8 | 344.1 | 371.1 | 380.3 | 11.7% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 888.5 | 1053.0 | 1117.7 | 1117.7 | 1.4% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 1152.0 | 1461.7 | 1461.7 | 1461.7 | 1.1% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2319.1 | 2343.4 | 2343.4 | 2343.4 | 0.7% | {'timeout': 2} |

## warm, session 38e723

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100}
- Corpus: seed 3, sha256 11fa903e602b, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 473 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 49 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.67 6.97 5.67 at the start, 7.35 7.52 5.92 at the end, client CPU in the measured window 8.4 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 801, 'crashed': 651, 'invalid': 327, 'passed': 219, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_OK': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 44.3, 2000 verdicts over 45.2 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 122.0 | 141.0 | 244.9 | 2124.9 |
| Startup (Vora) | 110 | 1890 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 15.6 | 18.5 | 86.1 | 140.8 |
| Execution (client) | 2000 | 0 | 106.0 | 123.0 | 150.4 | 2106.3 |
| This run's reset (Vora) | 1984 | 16 | 46.0 | 50.0 | 55.0 | 64.0 |
| Start to end of stream (client) | 2000 | 0 | 169.7 | 188.5 | 289.6 | 2168.0 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 121.9 | 140.5 | 200.1 | 272.5 | | |
| All classes | 2000 | 2000 | 0 | 122.0 | 141.0 | 244.9 | 2124.9 | 99.7% | {'failed': 801, 'crashed': 651, 'invalid': 327, 'passed': 219, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 121.1 | 142.4 | 217.0 | 264.4 | 9.6% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 122.4 | 140.4 | 191.5 | 244.9 | 47.9% | {'failed': 774, 'invalid': 114, 'crashed': 111, 'passed': 3} |
| syntax_error | 200 | 200 | 0 | 120.9 | 139.5 | 186.3 | 216.8 | 9.5% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 122.3 | 138.5 | 158.2 | 221.7 | 4.7% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 122.1 | 141.5 | 192.5 | 272.5 | 11.6% | {'invalid': 213, 'failed': 27} |
| crash | 240 | 240 | 0 | 121.5 | 139.6 | 174.7 | 209.3 | 11.4% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 719.2 | 867.7 | 923.9 | 923.9 | 2.1% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 909.5 | 1262.7 | 1262.7 | 1262.7 | 1.7% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2116.7 | 2124.9 | 2124.9 | 2124.9 | 1.2% | {'timeout': 2} |

## warm-no-reset (UNSAFE: no reset between runs, an experimental control only), session d5aee7

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100, 'reuse': 'unsafe_no_reset'}
- Corpus: seed 3, sha256 11fa903e602b, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 473 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 49 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.84 6.59 5.67 at the start, 6.22 6.90 5.81 at the end, client CPU in the measured window 7.6 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'passed': 219, 'crashed': 651, 'failed': 801, 'invalid': 327, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_SKIPPED': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 58.3, 2000 verdicts over 34.3 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 123.8 | 148.6 | 219.0 | 2142.3 |
| Startup (Vora) | 130 | 1870 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 15.6 | 20.2 | 67.0 | 126.6 |
| Execution (client) | 2000 | 0 | 107.7 | 130.6 | 148.1 | 2124.0 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 124.5 | 149.3 | 219.7 | 2142.9 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 123.6 | 147.8 | 188.8 | 237.9 | | |
| All classes | 2000 | 2000 | 0 | 123.8 | 148.6 | 219.0 | 2142.3 | 99.7% | {'passed': 219, 'crashed': 651, 'failed': 801, 'invalid': 327, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 121.9 | 147.3 | 182.7 | 218.9 | 9.4% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 123.5 | 148.5 | 192.4 | 237.9 | 47.3% | {'failed': 774, 'invalid': 114, 'crashed': 111, 'passed': 3} |
| syntax_error | 200 | 200 | 0 | 123.7 | 146.3 | 188.8 | 194.7 | 9.4% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 125.3 | 149.7 | 182.7 | 189.0 | 4.8% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 123.7 | 146.5 | 184.6 | 219.0 | 11.3% | {'invalid': 213, 'failed': 27} |
| crash | 240 | 240 | 0 | 123.8 | 147.2 | 174.3 | 193.2 | 11.4% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 712.2 | 898.4 | 921.6 | 921.6 | 2.5% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 884.7 | 1222.3 | 1222.3 | 1222.3 | 2.1% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2126.3 | 2142.3 | 2142.3 | 2142.3 | 1.6% | {'timeout': 2} |

## warm, session e592ef

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100}
- Corpus: seed 4, sha256 5bcc15e3b378, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 492 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 53 distinct), wrong_shape 240 (12.00%, 76 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.83 6.25 5.63 at the start, 6.99 6.75 5.83 at the end, client CPU in the measured window 8.3 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 791, 'crashed': 649, 'invalid': 334, 'passed': 224, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_OK': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 44.2, 2000 verdicts over 45.2 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 122.1 | 141.4 | 228.4 | 2122.7 |
| Startup (Vora) | 116 | 1884 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 15.4 | 18.2 | 77.9 | 122.0 |
| Execution (client) | 2000 | 0 | 106.1 | 123.6 | 140.7 | 2105.6 |
| This run's reset (Vora) | 1984 | 16 | 46.0 | 50.0 | 55.0 | 65.0 |
| Start to end of stream (client) | 2000 | 0 | 169.6 | 188.8 | 274.5 | 2174.6 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 122.0 | 140.7 | 196.2 | 236.9 | | |
| All classes | 2000 | 2000 | 0 | 122.1 | 141.4 | 228.4 | 2122.7 | 99.8% | {'failed': 791, 'crashed': 649, 'invalid': 334, 'passed': 224, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 122.3 | 141.8 | 228.4 | 236.9 | 9.6% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 122.1 | 141.2 | 180.3 | 221.7 | 47.9% | {'failed': 766, 'invalid': 119, 'crashed': 109, 'passed': 8} |
| syntax_error | 200 | 200 | 0 | 120.4 | 138.2 | 202.9 | 211.4 | 9.5% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 120.2 | 136.1 | 156.2 | 198.3 | 4.7% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 122.2 | 140.1 | 178.7 | 212.5 | 11.5% | {'invalid': 215, 'failed': 25} |
| crash | 240 | 240 | 0 | 123.6 | 141.3 | 180.2 | 221.6 | 11.5% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 719.5 | 1116.7 | 1119.4 | 1119.4 | 2.3% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 759.9 | 1259.5 | 1259.5 | 1259.5 | 1.5% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2121.2 | 2122.7 | 2122.7 | 2122.7 | 1.2% | {'timeout': 2} |

## warm-no-reset (UNSAFE: no reset between runs, an experimental control only), session 727342

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100, 'reuse': 'unsafe_no_reset'}
- Corpus: seed 4, sha256 5bcc15e3b378, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 492 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 53 distinct), wrong_shape 240 (12.00%, 76 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.95 6.02 5.62 at the start, 6.41 6.40 5.76 at the end, client CPU in the measured window 7.6 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'failed': 791, 'crashed': 649, 'invalid': 334, 'passed': 224, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_SKIPPED': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 58.1, 2000 verdicts over 34.4 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 124.0 | 148.7 | 279.1 | 2121.4 |
| Startup (Vora) | 134 | 1866 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 15.6 | 20.1 | 68.0 | 178.4 |
| Execution (client) | 2000 | 0 | 107.7 | 130.5 | 148.5 | 2107.3 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 124.6 | 149.4 | 279.9 | 2122.0 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 123.9 | 148.1 | 187.5 | 288.9 | | |
| All classes | 2000 | 2000 | 0 | 124.0 | 148.7 | 279.1 | 2121.4 | 99.7% | {'failed': 791, 'crashed': 649, 'invalid': 334, 'passed': 224, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 124.4 | 145.5 | 187.7 | 208.7 | 9.4% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 124.0 | 148.3 | 186.1 | 288.9 | 47.3% | {'failed': 766, 'invalid': 119, 'crashed': 109, 'passed': 8} |
| syntax_error | 200 | 200 | 0 | 122.7 | 148.0 | 182.1 | 202.6 | 9.3% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 121.7 | 145.0 | 187.5 | 245.1 | 4.6% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 124.0 | 146.6 | 179.9 | 203.1 | 11.2% | {'invalid': 215, 'failed': 25} |
| crash | 240 | 240 | 0 | 124.5 | 150.9 | 172.7 | 200.8 | 11.4% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 721.5 | 1118.6 | 1122.2 | 1122.2 | 2.9% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 811.0 | 1278.7 | 1278.7 | 1278.7 | 1.9% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2115.5 | 2121.4 | 2121.4 | 2121.4 | 1.5% | {'timeout': 2} |

## cold, session d2b0f0

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 0, 'max_size': 16}
- Corpus: seed 4, sha256 5bcc15e3b378, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 492 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 53 distinct), wrong_shape 240 (12.00%, 76 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.94 5.80 5.58 at the start, 15.67 8.98 6.72 at the end, client CPU in the measured window 9.1 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'crashed': 649, 'failed': 791, 'invalid': 334, 'passed': 224, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 0, cold 2000; not what this arm requires: 0 of 2000 (0.0%), against a bound of 0; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_RETIRED': 2000}
- Retired at check-in: {'shrink': 2000}. 2000 sandboxes, 2000 first runs, longest sandbox 1 runs
- Programs per second: 24.4, 2000 verdicts over 82.0 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 317.4 | 342.3 | 383.4 | 2323.8 |
| Startup (Vora) | 2000 | 0 | 149.0 | 175.0 | 201.0 | 249.0 |
| Startup (client) | 2000 | 0 | 170.0 | 193.8 | 220.7 | 265.4 |
| Execution (client) | 2000 | 0 | 147.1 | 161.5 | 180.5 | 2151.8 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 318.4 | 343.0 | 383.9 | 2324.6 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 317.3 | 341.6 | 371.5 | 420.8 | | |
| All classes | 2000 | 2000 | 0 | 317.4 | 342.3 | 383.4 | 2323.8 | 99.8% | {'crashed': 649, 'failed': 791, 'invalid': 334, 'passed': 224, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 316.5 | 338.3 | 359.8 | 377.6 | 9.7% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 316.9 | 341.1 | 372.3 | 420.8 | 48.8% | {'failed': 766, 'invalid': 119, 'crashed': 109, 'passed': 8} |
| syntax_error | 200 | 200 | 0 | 318.1 | 342.8 | 370.9 | 382.7 | 9.8% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 316.1 | 339.0 | 365.0 | 379.1 | 4.8% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 316.1 | 340.8 | 359.3 | 361.2 | 11.7% | {'invalid': 215, 'failed': 25} |
| crash | 240 | 240 | 0 | 319.5 | 347.1 | 367.1 | 383.4 | 11.8% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 925.1 | 1293.0 | 1318.3 | 1318.3 | 1.5% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 1007.3 | 1540.5 | 1540.5 | 1540.5 | 1.0% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2308.3 | 2323.8 | 2323.8 | 2323.8 | 0.7% | {'timeout': 2} |

## warm-no-reset (UNSAFE: no reset between runs, an experimental control only), session ec05f8

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100, 'reuse': 'unsafe_no_reset'}
- Corpus: seed 5, sha256 a19a31fb3b47, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 465 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 51 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.82 6.77 6.13 at the start, 6.80 7.18 6.29 at the end, client CPU in the measured window 7.7 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'passed': 217, 'failed': 771, 'invalid': 349, 'crashed': 661, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_SKIPPED': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 58.4, 2000 verdicts over 34.3 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 123.7 | 149.0 | 241.0 | 2120.2 |
| Startup (Vora) | 116 | 1884 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 15.7 | 19.8 | 77.7 | 146.7 |
| Execution (client) | 2000 | 0 | 107.6 | 130.0 | 148.9 | 2106.7 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 124.4 | 149.7 | 241.8 | 2121.3 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 123.5 | 148.2 | 194.1 | 270.5 | | |
| All classes | 2000 | 2000 | 0 | 123.7 | 149.0 | 241.0 | 2120.2 | 99.7% | {'passed': 217, 'failed': 771, 'invalid': 349, 'crashed': 661, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 123.9 | 150.4 | 195.3 | 235.0 | 9.5% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 123.3 | 148.1 | 185.9 | 270.5 | 47.3% | {'failed': 750, 'invalid': 130, 'crashed': 121, 'passed': 1} |
| syntax_error | 200 | 200 | 0 | 122.8 | 147.0 | 192.7 | 226.2 | 9.4% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 122.9 | 148.7 | 194.1 | 212.9 | 4.8% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 123.0 | 147.2 | 218.7 | 224.1 | 11.3% | {'invalid': 219, 'failed': 21} |
| crash | 240 | 240 | 0 | 126.3 | 148.2 | 163.4 | 199.4 | 11.4% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 624.5 | 875.8 | 876.5 | 876.5 | 2.4% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 876.2 | 1297.5 | 1297.5 | 1297.5 | 2.0% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2119.8 | 2120.2 | 2120.2 | 2120.2 | 1.5% | {'timeout': 2} |

## cold, session 8451ac

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 0, 'max_size': 16}
- Corpus: seed 5, sha256 a19a31fb3b47, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 465 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 51 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.56 6.29 6.03 at the start, 13.73 8.87 6.96 at the end, client CPU in the measured window 9.1 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'invalid': 349, 'failed': 771, 'passed': 217, 'crashed': 661, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 0, cold 2000; not what this arm requires: 0 of 2000 (0.0%), against a bound of 0; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_RETIRED': 2000}
- Retired at check-in: {'shrink': 2000}. 2000 sandboxes, 2000 first runs, longest sandbox 1 runs
- Programs per second: 24.4, 2000 verdicts over 81.9 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 318.1 | 342.4 | 386.4 | 2319.5 |
| Startup (Vora) | 2000 | 0 | 150.0 | 177.0 | 201.0 | 229.0 |
| Startup (client) | 2000 | 0 | 170.2 | 195.6 | 222.5 | 246.7 |
| Execution (client) | 2000 | 0 | 146.4 | 160.6 | 183.8 | 2159.4 |
| This run's reset (Vora) | 0 | 2000 | not measured | not measured | not measured | not measured |
| Start to end of stream (client) | 2000 | 0 | 318.9 | 343.4 | 387.0 | 2321.5 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 317.9 | 340.9 | 370.9 | 397.0 | | |
| All classes | 2000 | 2000 | 0 | 318.1 | 342.4 | 386.4 | 2319.5 | 99.8% | {'invalid': 349, 'failed': 771, 'passed': 217, 'crashed': 661, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 318.6 | 340.4 | 371.9 | 381.2 | 9.8% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 317.9 | 342.2 | 375.8 | 397.0 | 48.9% | {'invalid': 130, 'failed': 750, 'crashed': 121, 'passed': 1} |
| syntax_error | 200 | 200 | 0 | 316.7 | 335.9 | 366.6 | 381.1 | 9.7% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 318.0 | 348.1 | 365.3 | 371.0 | 4.9% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 317.9 | 339.0 | 358.6 | 360.7 | 11.7% | {'invalid': 219, 'failed': 21} |
| crash | 240 | 240 | 0 | 318.1 | 340.9 | 370.5 | 379.4 | 11.7% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 797.2 | 1039.9 | 1061.9 | 1061.9 | 1.3% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 1097.7 | 1504.6 | 1504.6 | 1504.6 | 1.0% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2314.1 | 2319.5 | 2319.5 | 2319.5 | 0.7% | {'timeout': 2} |

## warm, session 150aea

- Profile python-arc, backend gvisor, concurrency 8, shape {'size': 8, 'max_size': 8, 'max_runs': 100}
- Corpus: seed 5, sha256 a19a31fb3b47, hand_written 200 (10.00%, 10 distinct), mutated 1002 (50.10%, 465 distinct), syntax_error 200 (10.00%, 30 distinct), missing_transform 100 (5.00%, 51 distinct), wrong_shape 240 (12.00%, 77 distinct), crash 240 (12.00%, 50 distinct), slow 10 (0.50%, 10 distinct), memory_hungry 6 (0.30%, 6 distinct), timeout 2 (0.10%, 2 distinct)
- Server version v0.10.8 (--server-version), SDK 0.8.0 at None, git 272e731fb356bc702a4709a301f84c6eb0616e3c
- Host vora-mini, 16 CPUs, load 3.71 6.77 6.38 at the start, 6.64 7.11 6.51 at the end, client CPU in the measured window 8.4 s
- Image resolved via: containerd
- Measured 2000 of 2000 planned: 2000 with a verdict, 0 infrastructure failures
- Program verdicts: {'passed': 217, 'invalid': 349, 'crashed': 661, 'failed': 771, 'timeout': 2}
- Warmup, left out of everything below: 24 runs, 0 infrastructure failures
- Started warm 2000, cold 0; not what this arm requires: 0 of 2000 (0.0%), against a bound of 20; wrong reuse mode: 0
- Reset outcomes: {'POOL_RESET_OK': 1984, 'POOL_RESET_RETIRED': 16}
- Retired at check-in: {'max_runs': 16}. 24 sandboxes, 16 first runs, longest sandbox 100 runs
- Programs per second: 44.1, 2000 verdicts over 45.4 s of measured wall time at concurrency 8
- Denied syscalls: not measured. Vora's seccomp filter refuses calls without counting them, so no number exists.
- Blocked network attempts: not measured: network mode none has no gateway to count at, and Vora counts only in restricted mode

| Time, runs with a verdict, in ms | Count | Not reported | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| Wall-clock, start to exit (client) | 2000 | 0 | 122.7 | 142.2 | 269.8 | 2133.0 |
| Startup (Vora) | 97 | 1903 | under half reported | under half reported | under half reported | under half reported |
| Startup (client) | 2000 | 0 | 15.6 | 18.4 | 75.9 | 167.3 |
| Execution (client) | 2000 | 0 | 106.6 | 124.7 | 145.4 | 2119.1 |
| This run's reset (Vora) | 1984 | 16 | 46.0 | 50.0 | 57.0 | 64.0 |
| Start to end of stream (client) | 2000 | 0 | 170.4 | 189.9 | 314.0 | 2191.3 |

Vora leaves out `startup_ms` and `reset_ms` under 1 ms, and `reset_ms` when no reset ran, so a percentile of either covers only the slower runs it reported. A row with more left out than reported shows no percentile.

| Wall-clock by class, in ms | Planned | With a verdict | Infrastructure failures | p50 | p90 | p99 | Max | Share of slot time | Verdicts |
|---|---|---|---|---|---|---|---|---|---|
| Ordinary programs (all but memory_hungry, slow, timeout) | | 1982 | | 122.6 | 141.6 | 192.8 | 276.9 | | |
| All classes | 2000 | 2000 | 0 | 122.7 | 142.2 | 269.8 | 2133.0 | 99.8% | {'passed': 217, 'invalid': 349, 'crashed': 661, 'failed': 771, 'timeout': 2} |
| hand_written | 200 | 200 | 0 | 122.6 | 140.2 | 201.0 | 271.0 | 9.6% | {'passed': 200} |
| mutated | 1002 | 1002 | 0 | 122.4 | 141.9 | 185.3 | 269.8 | 47.9% | {'invalid': 130, 'failed': 750, 'crashed': 121, 'passed': 1} |
| syntax_error | 200 | 200 | 0 | 121.6 | 140.3 | 199.3 | 276.9 | 9.6% | {'crashed': 200} |
| missing_transform | 100 | 100 | 0 | 122.8 | 138.0 | 152.1 | 206.8 | 4.8% | {'crashed': 100} |
| wrong_shape | 240 | 240 | 0 | 123.4 | 142.1 | 200.9 | 234.1 | 11.6% | {'invalid': 219, 'failed': 21} |
| crash | 240 | 240 | 0 | 122.8 | 142.8 | 188.6 | 263.7 | 11.6% | {'crashed': 240} |
| slow | 10 | 10 | 0 | 621.1 | 865.8 | 875.1 | 875.1 | 2.0% | {'passed': 10} |
| memory_hungry | 6 | 6 | 0 | 875.9 | 1339.2 | 1339.2 | 1339.2 | 1.6% | {'passed': 6} |
| timeout | 2 | 2 | 0 | 2117.5 | 2133.0 | 2133.0 | 2133.0 | 1.2% | {'timeout': 2} |

