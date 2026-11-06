# About warm pools in vora-arc

A pool keeps running Vora sandboxes, so a program can start without waiting for a new
one. vora-arc can run its programs either way: `run_batch` creates a fresh sandbox per
run, and `pool_batch` borrows a member of a pool. `schedule.run_program` is the one
place that chooses, so `verify`, `vote` and `store` don't know which ran.

`vora-arc solve --pool` declares a pool with `VORA_MAX_CONCURRENCY` members, runs the
whole solve on it, and deletes it at the end. `solve` has no way to ask for a pool
without a reset.

To measure what a pool costs, see [How to run experiment 1](experiment-1.md).

## What a pooled run stores

| `runs` column | Fresh sandbox | Pool member |
|---|---|---|
| `warm_start` | `false` | `run.warm` |
| `reset_ms` | NULL | `done.reset_ms`, the run's own reset after it exited |
| `audit_log_id` | `exec.execution_id` | `exit.execution_id` |
| `startup_ms` | Client's clock, the create call | Client's clock, request to `run` frame |
| `exec_ms` | Client's clock, the exec call | Client's clock, `run` frame to `exit` frame |
| `peak_mem_bytes` | `stats()` | `exit.usage`, only when the kernel scoped the peak to this run |

`result_json` also keeps `prepared_reset_ms` (the earlier reset that prepared the
member), `reset_outcome` and `sandbox_run`.

The API's protojson leaves out zeros, so a missing `resetMs` means "not measured or under
a millisecond", and the API doesn't say which. vora-arc stores NULL for that and never 0.
`warm` is the exception. The SDK reads a missing `warm` as `false`, which is what protojson
means by it, so `warm_start` has no NULL. A run with no `run` frame at all is a Vora
failure and has no row.

`warm_start` means the member was running before the run asked for it. It doesn't mean the
member ran anything before: a pre-started member's first run is warm too, with
`sandbox_run` 1 and no prepared reset.

A pooled run's exit reason and counters decide its status, with the same order as a fresh
sandbox's `stats()`: `oom_kills`, then `pids_limit_hits`, then the reason. The counters
come first because Vora reports `EXITED` when a program hits the pids limit and the runner
still exits 0. A kill can also take the stream down before `exit`. `pool_result` then
reads the run's record from `pool.execs`, and only calls the run a Vora failure if that
record shows no kill.

## What vora-arc doesn't count

`denied_syscalls` has no source. Vora's seccomp filter refuses a call without counting it,
so reports say "not measured" and nothing stores a number.

`blocked_net_attempts` would come from `egress_denied`, which counts decisions of the egress
gateway. It exists only in `restricted` mode, and it is a floor there, because traffic that
never reaches the gateway isn't counted. Pools refuse that mode, and both shipped profiles
use `none`, which has no interface to count at. Reports say "not measured".

## Which failures repeat

`client._retrying` is the only retry on a run. vora-arc never passes the SDK's `retry=` on a
run. `run_batch` and `pool_batch` share the loop. `vora-arc bench` doesn't use it, so a
refusal shows as a failed run.

| Error | Repeated | Why |
|---|---|---|
| Transport error before any output | Yes | Nothing came back |
| `RateLimitedError` (429) | Yes, waiting at least `Retry-After` | Nothing ran |
| `UnavailableError` (503) | Yes, waiting at least `Retry-After` | Usually nothing ran. A lost runner can answer 503 after the program started, and a repeat is still safe because an ARC program is a pure function of its input |
| `GatewayTimeoutError` (504) | No | Each attempt can wait 7 minutes for a first frame |
| `PoolNotLoadedError`, `PoolNotOnRunnerError`, other `ConflictError` | No | The pool won't recover on its own |
| `PoolRunError`, a break after the first frame | No | The program may have run, and this is how a kill often looks |

After the last retry, the error reaches `schedule`, which records a Vora failure for that
program and goes on with the others. A lost pool fails every remaining program this way,
and `solve` exits non-zero. Nothing declares the pool again in the middle of a run.

## What a pool asks of a profile

A pool's spec is narrower than a plain sandbox's. The shipped profiles meet its rules, and
`tests/test_pool_client.py` fails if one stops meeting them.

| Rule, from `internal/pool/spec.go` | `python-arc` (gVisor) | `python-arc-bwrap` |
|---|---|---|
| Network mode must be `none`, so `restricted` is refused | `none` | `none` |
| `pids` floor: gVisor 64, bwrap 12 | 64, exactly the floor | 16 |
| The template sets no TTL | vora-arc leaves `ttl_seconds` out | The same |

A profile that breaks a rule gets a 400 at declare, and `vora-arc` exits with the API's
message and the profile's name.

These rules aren't the whole requirement. A pool with `size` above 0 also needs a backend that can
reset a sandbox, and that depends on the Vora you run:

| Backend | What a pool with members needs |
|---|---|
| `bwrap` | Vora v0.10.8 or later |
| `gvisor` | Vora v0.10.8 or later, which has [vorash/vora#150](https://github.com/vorash/vora/pull/150) |

On an older Vora, `solve --pool` with `python-arc`, and the `warm` and `warm-no-reset` arms, get
this at declare, so nothing runs and the command exits non-zero:

```text
pool vora-arc-bench-warm-1a2b3c was refused for profile python-arc: pool: backend cannot reset sandboxes: "gvisor"
```

The `cold` arm still declares on that Vora, because a pool of size 0 reuses nothing. This comes from
reading `internal/pool/spec.go`, and no real server has answered it here.

Under bwrap, an idle sandbox holds 10 or 11 tasks, so `pids = 16` leaves the workload 5.
The runner needs 2: itself and one worker. Under gVisor the limit counts the Sentry's
host threads and not the program's processes, so it doesn't stop a fork bomb there.
`tests/test_hostile.py` already expects that.

## Why three hostile tests still fail on purpose

Each stays a strict `xfail`, so the test fails if Vora's behaviour changes. These tests need
a sandbox host to run.

### Writing to `/workspace` and `/root` succeeds

The spec asks for a read-only root with only `/tmp` writable. Vora binds `/workspace` and
`/root` read-write on both backends (`internal/runtime/bwrap/args.go`,
`internal/runtime/gvisor/bundle.go`), and its file API serves those two paths
(`internal/sandbox/files.go`). That's a design choice for a general sandbox, and an ARC
solver is no reason to change it. The rest of the root is read-only, and `write_slash` and
`write_usr` pass.

The property that matters for a program is that a later program can't see the write. A fresh
sandbox gets that from being new. A pool gets it from the reset, and
`test_a_write_does_not_survive_into_the_next_run` checks it with a one-member pool, where
run B must land on run A's sandbox. `test_without_a_reset_the_same_write_does_survive` is its
control: on a no-reset pool the file is still there, which shows the first test can fail.

### Filling `/tmp` past 16 MB succeeds

Vora mounts `/tmp` as a tmpfs with no size option on either backend (bwrap's `--tmpfs` with no
`--size`, gVisor's mount options `nosuid,nodev,mode=1777`), so `fill_tmp`'s 32 MB fits. The spec's
16 MB would need a new option in Vora, and this project doesn't add one for ARC.

What bounds `/tmp` is the sandbox's memory limit. The kernel charges tmpfs pages to the
memory cgroup of the process that writes them, so under bwrap they count against
`memory.max` with the program's own memory. Under gVisor the Sentry holds them, and the Sentry
runs in the sandbox's cgroup. `test_filling_tmp_runs_into_the_memory_limit` expects `KILLED_OOM`
from a program that writes 2 GB. It hasn't run yet, so treat this paragraph as read from the
code and not as measured. Two limits sit beside it:

- Vora sets a swap limit of 0 (`memory.swap.max` in `internal/cgroup/subtree.go`, `MemorySwapMax` in
  `internal/cgroup/systemd.go`), so pages charged to the sandbox can't move to swap, tmpfs pages included.
- The sandbox's disk quota covers the paths in `quotaPaths`, and `/tmp` isn't one of them.

The spec's other demand for this case is that the next run on the same sandbox starts clean.
`test_a_write_does_not_survive_into_the_next_run` covers that too, with `fill_tmp` as its writer.
