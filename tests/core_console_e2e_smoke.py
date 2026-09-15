"""Actual Core Textual UI -> Memory HTTP with synthetic project data, no subscription CLI."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.environ["MEMORY_CORE_SOURCE"])

from isekai.cli.console.app import WatchApp  # noqa: E402
from isekai.cli.console.model import DashboardSource, Selection  # noqa: E402
from isekai.memory.client import MemoryMcpClient  # noqa: E402
from isekai.memory.config import MemoryConfig  # noqa: E402
from textual.widgets import DataTable, Tabs  # noqa: E402

ALLOWED = {"memory_collaboration_overview", "memory_collaboration_list", "memory_presence_policy_get",
           "memory_presence_list", "memory_presence_users", "memory_usage_summary", "memory_collaboration_events"}


class ReadGuard:
    def __init__(self, token):
        config = MemoryConfig(os.environ["MEMORY_BASE_URL"] + "/mcp", "synthetic", "test")
        self.client = MemoryMcpClient(config, SimpleNamespace(resolve=lambda _: token))
        self.calls = []

    def call_tool(self, name, args, **limits):
        assert name in ALLOWED, "TUI attempted an unexpected or mutating tool"
        self.calls.append(name)
        return self.client.call_tool(name, args, **limits)


async def settled(app, pilot):
    for _ in range(400):
        await pilot.pause(0.02)
        if app.poll.in_flight is None:
            assert app.poll.snapshot is not None, app.poll.error_code
            return
    raise AssertionError("TUI HTTP refresh did not finish within the test budget")


async def run_ui(token_name, actor, project_admin, directory):
    client = ReadGuard(os.environ[token_name])
    project = os.environ["MEMORY_TEST_PROJECT_ID"]
    app = WatchApp(DashboardSource(client, project, actor_id=actor), manage=project_admin,
                   selection=Selection(scope="project" if project_admin else "mine"))
    async with app.run_test(size=(120, 36)) as pilot:
        await settled(app, pilot)
        assert app.poll.snapshot["overview"]["identity"]["project_admin"] is project_admin
        for view in ("work", "inbox", "sent", "checkpoints", "users", "sessions", "usage", "admin"):
            app.query_one("#views", Tabs).active = "view-" + view
            await settled(app, pilot)
            assert app.poll.snapshot["overview"]["actor_id"] == actor
            assert app.poll.snapshot["overview"]["project_id"] == project
            table = app.query_one("#records", DataTable)
            if table.row_count:
                table.focus()
                before = len(client.calls)
                await pilot.press("enter")
                assert len(client.calls) == before
                await pilot.press("escape")
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert app.query_one("#inline-detail").has_class("hidden")
        if directory is not None:
            (directory / (actor + "-synthetic.svg")).write_text(app.export_screenshot(title="Synthetic Memory collaboration"))
    assert app.poll.closed
    return len(client.calls)


def once(directory):
    profile = directory / "profile.json"
    profile.write_text(json.dumps({"schema_version": 1, "project_id": os.environ["MEMORY_TEST_PROJECT_ID"],
        "endpoint": os.environ["MEMORY_BASE_URL"] + "/mcp", "organization_id": "synthetic",
        "credential_ref": "console", "expected_actor_id": "recipient-two"}))
    profile.chmod(0o600)
    env = {**os.environ, "PYTHONPATH": os.environ["MEMORY_CORE_SOURCE"],
           "ISEKAI_MEMORY_CREDENTIAL_CONSOLE": os.environ["MEMORY_RECIPIENT_TOKEN"]}
    result = subprocess.run([sys.executable, "-m", "isekai.cli", "--project", str(directory / "not-a-checkout"),
        "--output", "json", "watch", "--profile", str(profile), "--once", "--view", "inbox"],
        cwd=directory, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, "watch --once failed (raw response deliberately not printed)"
    assert json.loads(result.stdout)["result"]["overview"]["actor_id"] == "recipient-two"
    assert not (directory / "not-a-checkout").exists()


def main():
    with tempfile.TemporaryDirectory(prefix="isekai-console-http-") as temporary:
        root = Path(temporary)
        once(root)
        first = asyncio.run(run_ui("MEMORY_ADMIN_TOKEN", "e2e-user", True, root))
        second = asyncio.run(run_ui("MEMORY_RECIPIENT_TOKEN", "recipient-two", False, root))
    print(json.dumps({"core_console_http": True, "admin_and_recipient_same_ui": True,
                      "no_mutating_tools": True, "no_local_checkout_or_state": True,
                      "bounded_queries": first + second, "real_cli_account": False}))


if __name__ == "__main__":
    main()
