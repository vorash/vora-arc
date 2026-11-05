from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from importlib import util as importlib_util
from pathlib import Path

import psycopg
import pytest


@dataclass(frozen=True)
class Postgres:
    socket_dir: Path

    def url(self, database: str) -> str:
        return f"host={self.socket_dir} dbname={database} user=vora_arc"


def _postgres_bin_dir() -> Path | None:
    """Binaries on PATH, else the ones the dev dependency pixeltable-pgserver ships."""
    on_path = shutil.which("initdb")
    if on_path and shutil.which("pg_ctl"):
        return Path(on_path).parent
    spec = importlib_util.find_spec("pixeltable_pgserver")
    if spec is None or spec.origin is None:
        return None
    candidate = Path(spec.origin).parent / "pginstall" / "bin"
    return candidate if (candidate / "initdb").exists() else None


@pytest.fixture
def ctrl_c_interrupts() -> Iterator[None]:
    """A shell starts background jobs with SIGINT ignored, and asyncio then wouldn't see it."""
    previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    yield
    signal.signal(signal.SIGINT, previous)


@pytest.fixture(scope="session")
def postgres(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Postgres]:
    """A throwaway unprivileged cluster: temp dir, Unix socket only, gone at the end."""
    bin_dir = _postgres_bin_dir()
    if bin_dir is None or os.geteuid() == 0:
        pytest.skip(
            "store tests need PostgreSQL: put initdb and pg_ctl on PATH or install the dev group "
            "(pixeltable-pgserver), and don't run as root"
        )
    data = tmp_path_factory.mktemp("pg") / "data"
    # A Unix socket path is limited to about 100 characters, and pytest's temp paths can be longer.
    with tempfile.TemporaryDirectory(prefix="vapg", dir="/tmp") as socket_dir:
        subprocess.run(
            [bin_dir / "initdb", "-D", data, "-U", "vora_arc", "--auth=trust", "--no-sync", "-E", "UTF8"],
            check=True,
            capture_output=True,
        )
        options = f"-c listen_addresses='' -c unix_socket_directories={socket_dir} -c fsync=off"
        subprocess.run(
            [bin_dir / "pg_ctl", "-w", "-D", data, "-l", data / "server.log", "-o", options, "start"],
            check=True,
            capture_output=True,
        )
        try:
            yield Postgres(Path(socket_dir))
        finally:
            subprocess.run([bin_dir / "pg_ctl", "-D", data, "-m", "immediate", "stop"], check=False, capture_output=True)


@pytest.fixture
def database_url(postgres: Postgres, request: pytest.FixtureRequest) -> str:
    """A new empty database for this test."""
    name = "t_" + format(abs(hash(request.node.nodeid)), "x")
    with psycopg.connect(postgres.url("postgres"), autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}"'.encode())
    return postgres.url(name)
