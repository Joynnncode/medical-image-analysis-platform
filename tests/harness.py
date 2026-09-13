"""Stands up the whole local stack for a test run, then takes it down again.

One run brings up four things:

  * a throwaway Postgres database on whatever server is already running, so
    the suite never touches the dev database the app normally uses,
  * the AI service stub from `stub_ai_service.py`,
  * a fake GitHub from `stub_github.py`, for the OAuth sign-in,
  * the real API, built from source and pointed at both.

The frontend is not started. Everything a click in the browser does reaches
the API as an HTTP call, and those calls are what the suite makes.

Nothing here needs Docker. It needs a Postgres server (Homebrew's
`postgresql@16` is what this was written against), the .NET SDK, and the
Python dependencies in requirements.txt.
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
import requests

import stub_github

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
API_PROJECT = REPO_ROOT / "backend" / "MedicalImageAnalysis.Api"
API_DLL = API_PROJECT / "bin" / "Debug" / "net10.0" / "MedicalImageAnalysis.Api.dll"

# Long enough for a cold `dotnet` start on a laptop, short enough that a
# genuinely broken stack fails the run instead of hanging it.
API_START_TIMEOUT_S = 90
STUB_START_TIMEOUT_S = 30

# Test-only, and only ever reachable on loopback. Has to clear the 32-byte
# floor the HS256 signing key needs.
TEST_JWT_KEY = "test-only-key-not-a-secret-32chars-min-xxxxx"


class StackError(RuntimeError):
    """The stack could not be brought up. Carries the relevant log tail."""


def free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _admin_dsn(dbname: str = "postgres") -> str:
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    user = os.environ.get("PGUSER") or os.environ.get("USER", "postgres")
    dsn = f"host={host} port={port} user={user} dbname={dbname}"
    password = os.environ.get("PGPASSWORD")
    if password:
        dsn += f" password={password}"
    return dsn


def _npgsql_connection_string(dbname: str) -> str:
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    user = os.environ.get("PGUSER") or os.environ.get("USER", "postgres")
    parts = [f"Host={host}", f"Port={port}", f"Database={dbname}", f"Username={user}"]
    password = os.environ.get("PGPASSWORD")
    if password:
        parts.append(f"Password={password}")
    return ";".join(parts)


def _wait_for_http(url: str, timeout_s: float, process: subprocess.Popen, log: Path):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise StackError(
                f"{url} never came up: the process exited with code "
                f"{process.returncode}.\n{_log_tail(log)}"
            )
        try:
            if requests.get(url, timeout=2).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.3)

    raise StackError(f"{url} did not answer within {timeout_s}s.\n{_log_tail(log)}")


def _log_tail(log: Path, lines: int = 40) -> str:
    if not log.exists():
        return f"(no output captured in {log})"
    tail = log.read_text(errors="replace").splitlines()[-lines:]
    return f"--- last {len(tail)} lines of {log.name} ---\n" + "\n".join(tail)


@dataclass
class Stack:
    """A running stack. The URLs include no trailing slash."""

    api_url: str
    stub_url: str
    github_url: str
    database: str
    storage_root: Path
    log_dir: Path
    _processes: list[subprocess.Popen] = field(default_factory=list)

    def set_ai_behaviour(self, mode: str = "ok", delay_seconds: float = 0.0):
        """Tell the stub how to answer the next segmentation.

        mode is "ok", "busy" (503, as when another run holds the slot) or
        "fail" (500, as when inference raises).
        """
        response = requests.post(
            f"{self.stub_url}/__control",
            json={"mode": mode, "delay_seconds": delay_seconds},
            timeout=5,
        )
        response.raise_for_status()

    def set_github_user(self, github_id: int, login: str, decline: bool = False):
        """Choose who the fake GitHub signs in next, or have them decline on
        the consent screen."""
        response = requests.post(
            f"{self.github_url}/__control",
            json={"id": github_id, "login": login, "decline": decline},
            timeout=5,
        )
        response.raise_for_status()


def _start_stub(app: str, port: int, log: Path) -> subprocess.Popen:
    handle = log.open("w")
    process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", app,
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=TESTS_DIR,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    _wait_for_http(f"http://127.0.0.1:{port}/health", STUB_START_TIMEOUT_S, process, log)
    return process


def _build_api(log_dir: Path):
    if os.environ.get("MEDIMG_TEST_SKIP_BUILD") == "1" and API_DLL.exists():
        return

    log = log_dir / "dotnet-build.log"
    with log.open("w") as handle:
        result = subprocess.run(
            ["dotnet", "build", str(API_PROJECT / "MedicalImageAnalysis.Api.csproj"),
             "-c", "Debug", "--nologo"],
            cwd=REPO_ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )

    if result.returncode != 0:
        raise StackError(f"The API did not build.\n{_log_tail(log, lines=30)}")


def _start_api(port: int, dbname: str, stub_url: str, github_url: str,
               storage_root: Path, log_dir: Path) -> subprocess.Popen:
    # The built DLL is run directly rather than through `dotnet run`, because
    # `dotnet run` applies Properties/launchSettings.json and would bind port
    # 5283 instead of the one this run picked.
    env = {
        **os.environ,
        "ASPNETCORE_ENVIRONMENT": "Development",
        "ASPNETCORE_URLS": f"http://127.0.0.1:{port}",
        "ConnectionStrings__Default": _npgsql_connection_string(dbname),
        "AiService__BaseUrl": stub_url,
        "Jwt__Key": TEST_JWT_KEY,
        "Storage__Root": str(storage_root),
        "GitHub__ClientId": stub_github.CLIENT_ID,
        "GitHub__ClientSecret": stub_github.CLIENT_SECRET,
        "GitHub__AuthorizationEndpoint": f"{github_url}/login/oauth/authorize",
        "GitHub__TokenEndpoint": f"{github_url}/login/oauth/access_token",
        "GitHub__UserInformationEndpoint": f"{github_url}/user",
    }

    log = log_dir / "api.log"
    handle = log.open("w")
    process = subprocess.Popen(
        ["dotnet", str(API_DLL)],
        cwd=API_PROJECT,
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    _wait_for_http(f"http://127.0.0.1:{port}/health", API_START_TIMEOUT_S, process, log)
    return process


def _create_database(name: str):
    try:
        with psycopg.connect(_admin_dsn(), autocommit=True, connect_timeout=5) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
    except psycopg.OperationalError as exc:
        raise StackError(
            "Could not reach a Postgres server to create the test database.\n"
            f"Tried: {_admin_dsn()}\n"
            "Start one with `brew services start postgresql@16`, or point "
            "PGHOST / PGPORT / PGUSER / PGPASSWORD at another server.\n"
            f"{exc}"
        ) from exc


def _drop_database(name: str):
    with psycopg.connect(_admin_dsn(), autocommit=True, connect_timeout=5) as conn:
        # The API's connection pool may not have finished letting go yet.
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


def start_stack(keep_logs: bool = False) -> tuple[Stack, "callable"]:
    """Bring the stack up. Returns the stack and a function that tears it down."""
    run_id = uuid.uuid4().hex[:8]
    dbname = f"medimg_test_{run_id}"
    work_dir = Path(tempfile.mkdtemp(prefix=f"medimg-test-{run_id}-"))
    log_dir = work_dir / "logs"
    log_dir.mkdir(parents=True)
    storage_root = work_dir / "storage"
    storage_root.mkdir()

    processes: list[subprocess.Popen] = []
    created_db = False

    def stop():
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        if created_db:
            _drop_database(dbname)
        if keep_logs:
            print(f"\nStack logs kept in {log_dir}")
        else:
            shutil.rmtree(work_dir, ignore_errors=True)

    try:
        _create_database(dbname)
        created_db = True

        stub_port = free_port()
        processes.append(_start_stub("stub_ai_service:app", stub_port, log_dir / "ai-stub.log"))
        stub_url = f"http://127.0.0.1:{stub_port}"

        github_port = free_port()
        processes.append(_start_stub("stub_github:app", github_port, log_dir / "github-stub.log"))
        github_url = f"http://127.0.0.1:{github_port}"

        _build_api(log_dir)
        api_port = free_port()
        processes.append(_start_api(api_port, dbname, stub_url, github_url, storage_root, log_dir))

        stack = Stack(
            api_url=f"http://127.0.0.1:{api_port}",
            stub_url=stub_url,
            github_url=github_url,
            database=dbname,
            storage_root=storage_root,
            log_dir=log_dir,
            _processes=processes,
        )
        return stack, stop
    except Exception:
        stop()
        raise
