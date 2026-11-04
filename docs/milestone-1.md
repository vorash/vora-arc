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
include one round trip each. Nobody has explained the 10x create gap yet. A
guess: bwrap starts every sandbox as a `systemd-run` transient unit.

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
| 2 GB allocation: peak memory (bwrap only) | the OOM kill is reported, but Vora returns no memory stats for the dead sandbox (vorash/vora#108); gVisor reports it | Vora |
| env / `/proc` probe (bwrap only) | bwrap sandboxes inherit the systemd user manager's environment: `SSH_AUTH_SOCK`, `DBUS_SESSION_BUS_ADDRESS`, `XDG_RUNTIME_DIR` and more. The paths are not mounted in the sandbox, so the sockets are unreachable (vorash/vora#107). | Vora |

## Not done

- Spec fields that network mode `none` can't observe (blocked network
  attempts, denied syscalls) are not reported.
