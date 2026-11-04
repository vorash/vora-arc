# Milestone 1: harness

Built: the in-sandbox runner and `vora/arc` image (`sandbox/`), task loading
and verification, ten hand-written solutions, the client and profiles, the
hostile suite, and `vora-arc run-solution`. No Vora code changed.

## Result on vora-mini (2026-11-04)

Vora v0.10.0, bwrap backend (`profiles/python-arc-bwrap.toml`); the runner
there has no gVisor. Run with:

```sh
VORA_API_URL=… VORA_API_KEY=… VORA_ARC_PROFILE=profiles/python-arc-bwrap.toml \
  uv run pytest -m sandbox
```

- All 10 solutions report `passed`, each confirmed by an identical second run.
- Hostile suite: 10 pass, 5 expected failures, 0 unexpected.
- One solution run, measured from the laptop through an SSH tunnel: sandbox
  create 6.5 s the first time the image was used, 1.1 s after; exec 60-80 ms.

## Expected failures

| Test | Why | Owner |
|---|---|---|
| write to `/workspace`, `/root` | writable in every Vora sandbox | M2, Vora profile work |
| fill `/tmp` past 16 MB | `/tmp` size is not configurable | M2, Vora profile work |
| 2 GB allocation: peak memory | the OOM kill is reported, but Vora returns no memory stats for the dead sandbox | Vora |
| env / `/proc` probe (bwrap only) | bwrap sandboxes inherit the systemd user manager's environment: `SSH_AUTH_SOCK`, `DBUS_SESSION_BUS_ADDRESS`, `XDG_RUNTIME_DIR` and more. The paths are not mounted in the sandbox, so the sockets are unreachable. | Vora |

## Not done

- gVisor: the spec's profile asks for it; vora-mini needs a root gVisor
  runner first.
- Spec fields that network mode `none` cannot observe (blocked network
  attempts, denied syscalls) are not reported.
