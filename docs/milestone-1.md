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

### Update: Vora v0.10.5 (2026-11-05)

The sandbox suite was re-run on v0.10.5. The hostile suite gives gVisor 12 pass, 3
expected failures, and bwrap 12 pass, 3 expected failures, the same set on both. The
hand-written solutions pass 10 / 10 on both. bwrap gained two: the 2 GB allocation's
peak memory (vorash/vora#108, since v0.10.3), and the environment probe
(vorash/vora#107, since v0.10.5).

**Skip v0.10.3 on bwrap.** Its OOM shim needs OS threads that count against `pids`,
so at this profile's `pids = 16` 8 of 40 runs of the solution suite failed. On v0.10.4,
40 of 40 passed, and on v0.10.5 25 of 25. A long-lived sandbox is still at risk at this limit: after about 50
execs in one sandbox on a 16-core host, `vora-init`'s threads use up the limit
(vorash/vora#125). This harness runs one exec per sandbox, so it isn't affected yet,
but warm pools would be.

The 10x create gap above was not bwrap or systemd. gRPC's reconnect backoff made the
runner wait about 1 s before retrying the agent's socket (vorash/vora#114, fixed in
v0.10.2). Measured on vora-mini through the CLI, a different method from the table
above, v0.10.2 creates a bwrap sandbox in 183-187 ms and a gVisor sandbox in 108-125 ms.
A `/bin/true` exec on bwrap through the CLI went from a median 19.8 ms on v0.10.2 to
7.9 ms on v0.10.4.

A gVisor sandbox that goes over its memory limit still dies, and later execs report
`EXITED` with exit code 128 (vorash/vora#120).

## Expected failures

| Test | Why | Owner |
|---|---|---|
| write to `/workspace`, `/root` | writable in every Vora sandbox | M2, Vora profile work |
| fill `/tmp` past 16 MB | `/tmp` size is not configurable | M2, Vora profile work |

## Not done

- Spec fields that network mode `none` can't observe (blocked network
  attempts, denied syscalls) are not reported.
