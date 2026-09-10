"""Run real HTTP and stdio entry points against an explicitly selected test DB.

Requires MEMORY_TEST_DATABASE_URL pointing to a disposable DB migrated to head.
Creates unique project tokens/data, starts a loopback-only child server, runs both
smoke scripts, stops the server and revokes its tokens. Never prints credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from isekai_memory.config import Settings
from isekai_memory.server.auth import hash_token
from isekai_memory.store import queries
from isekai_memory.store.database import close_pool, health_check, init_pool


async def tokens(settings: Settings, project: str) -> tuple[dict, list[str]]:
    environment = {}
    token_ids = []
    await init_pool(settings)
    try:
        await health_check()
        for key, target, scopes in [
            ("MEMORY_ADMIN_TOKEN", project, ["admin"]),
            ("MEMORY_READ_TOKEN", project, ["read"]),
            ("MEMORY_CROSS_PROJECT_TOKEN", project + "-other", ["read", "write"]),
        ]:
            raw = secrets.token_urlsafe(32)
            row = await queries.create_token(token_hash=hash_token(raw), project_id=target, user_id="e2e-user", scopes=scopes, expires_at=None)
            environment[key] = raw
            token_ids.append(str(row["id"]))
    finally:
        await close_pool()
    return environment, token_ids


async def revoke(settings: Settings, token_ids: list[str]) -> None:
    await init_pool(settings)
    try:
        for token_id in token_ids:
            await queries.revoke_token(token_id=token_id)
    finally:
        await close_pool()


def main() -> None:
    dsn = os.environ.get("MEMORY_TEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("MEMORY_TEST_DATABASE_URL must explicitly select a disposable, migrated database")
    settings = Settings(database_url=dsn)
    project = "smoke-" + uuid4().hex
    credentials, token_ids = asyncio.run(tokens(settings, project))
    environment = {
        **os.environ, **credentials, "ISEKAI_MEMORY_DATABASE_URL": dsn,
        "ISEKAI_MEMORY_AUTH_ENABLED": "true", "MEMORY_TEST_PROJECT_ID": project,
    }
    root = Path(__file__).resolve().parents[1]
    try:
        with socket.socket() as bound:
            bound.bind(("127.0.0.1", 0))
            port = bound.getsockname()[1]
        environment["MEMORY_BASE_URL"] = f"http://127.0.0.1:{port}"
        with tempfile.TemporaryFile(mode="w+") as server_log:
            process = subprocess.Popen(
                [sys.executable, "-m", "isekai_memory.main", "--mode", "http", "--host", "127.0.0.1", "--port", str(port)],
                cwd=root, env=environment, stdout=server_log, stderr=server_log,
            )
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        with urllib.request.urlopen(environment["MEMORY_BASE_URL"] + "/ready", timeout=1) as response:
                            if json.load(response).get("schema_revision") == "008":
                                break
                    except (OSError, urllib.error.URLError):
                        time.sleep(0.05)
                else:
                    raise RuntimeError("Test HTTP server did not become ready")
                for script in ("e2e_smoke.py", "stdio_e2e_smoke.py", "generation_e2e_smoke.py", "skills_e2e_smoke.py", "team_e2e_smoke.py"):
                    subprocess.run([sys.executable, str(root / "tests" / script)], cwd=root, env=environment, check=True, timeout=45)
                if os.environ.get("MEMORY_CORE_PYTHON") and os.environ.get("MEMORY_CORE_SOURCE"):
                    subprocess.run([os.environ["MEMORY_CORE_PYTHON"], str(root / "tests" / "core_recall_e2e_smoke.py")], cwd=root, env=environment, check=True, timeout=45)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    finally:
        asyncio.run(revoke(settings, token_ids))


if __name__ == "__main__":
    main()
