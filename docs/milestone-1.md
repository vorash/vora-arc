# Milestone 1: harness

Built: the in-sandbox runner and `vora/arc` image (`sandbox/`), task loading
and verification, ten hand-written solutions, the client and profiles, the
hostile suite, and `vora-arc run-solution`. No Vora code changed.

## Result on vora-mini (2026-11-04)

Vora v0.10.1 on vora-mini. A root runner serves gVisor (runsc release-20260914.0,
kvm platform) and the non-root runner serves bwrap. Run with:

```sh
VORA_API_URL=… VORA_API_KEY=… uv run pytest -m sandbox            # gVisor, profiles/python-arc.toml
VORA_ARC_PROFILE=profiles/python-arc-bwrap.toml … uv run pytest -m sandbox
```

| | gVisor | bwrap |
|---|---|---|
| hand-written solutions `passed` (each confirmed by an identical re-run) | 10 / 10 | 10 / 10 |
| hostile suite | 12 pass, 3 expected failures | 10 pass, 5 expected failures |
| sandbox create (6 runs of one task) | 95-128 ms | 1118-1146 ms |
| runner exec (same runs) | 88-98 ms | 60-61 ms |

Timings were measured from the laptop through an SSH tunnel to the API, so they
include one round trip each.

### Update: Vora v0.10.3 (2026-11-04)

The sandbox suite was re-run on v0.10.3, and the hostile suite now gives gVisor
12 pass, 3 expected failures, and bwrap 11 pass, 4 expected failures. The
hand-written solutions pass 10 / 10 on both. The bwrap gain is the 2 GB
allocation's peak memory (vorash/vora#108): since v0.10.3 a bwrap sandbox
survives an OOM in an exec and keeps its stats.

The 10x create gap above was not bwrap or systemd. gRPC's reconnect backoff made
the runner wait about 1 s before retrying the agent's socket (vorash/vora#114,
fixed in v0.10.2). Measured on vora-mini through the CLI, a different method from
the table above, v0.10.2 creates a bwrap sandbox in 183-187 ms and a gVisor sandbox
in 108-125 ms. The bwrap runner exec is also cheaper since v0.10.3: a `/bin/true`
exec through the CLI went from a median 19.8 ms to 10.3 ms.

v0.10.3 did not change gVisor. A gVisor sandbox that goes over its memory limit
still dies, and later execs report `EXITED` with exit code 128 (vorash/vora#120).

**pids under gVisor.** The spec's 16-process limit can't start a gVisor
sandbox. The host cgroup also counts runsc's own threads: 30 or fewer fail to
start, 32 is flaky, and 40 or more always works. `python-arc.toml` uses 64.
Because guest processes aren't host processes, the fork bomb runs into the
256 MB memory cap (`KILLED_OOM`) instead of the process limit. Either way the
run is killed, and the host is not affected.

## Expected failures

| Test | Why | Owner |
|---|---|---|
| write to `/workspace`, `/root` | writable in every Vora sandbox | M2, Vora profile work |
| fill `/tmp` past 16 MB | `/tmp` size is not configurable | M2, Vora profile work |
| env / `/proc` probe (bwrap only) | bwrap sandboxes inherit the systemd user manager's environment: `SSH_AUTH_SOCK`, `DBUS_SESSION_BUS_ADDRESS`, `XDG_RUNTIME_DIR` and more. The paths are not mounted in the sandbox, so the sockets are unreachable (vorash/vora#107). | Vora |

## Not done

- Spec fields that network mode `none` can't observe (blocked network
  attempts, denied syscalls) are not reported.
