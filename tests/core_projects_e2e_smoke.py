"""Two real project tokens, one denied target: global Core UI / CLI -> Memory HTTP."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.environ["MEMORY_CORE_SOURCE"])

from isekai.cli.console.portfolio import PortfolioSource  # noqa: E402
from isekai.cli.console.portfolio_app import PortfolioApp  # noqa: E402
from isekai.cli.console.project_registry import ProjectEntry, ProjectRegistry  # noqa: E402
from isekai.memory.client import MemoryMcpClient  # noqa: E402
from textual.widgets import DataTable  # noqa: E402

ALLOWED = {"memory_collaboration_overview", "memory_presence_users", "memory_usage_summary"}


def factory(profile):
    token = {"portfolio-main": "MEMORY_ADMIN_TOKEN", "portfolio-other": "MEMORY_CROSS_PROJECT_TOKEN"}[profile.memory.credential_ref]
    client = MemoryMcpClient(profile.memory, SimpleNamespace(resolve=lambda _: os.environ[token]))
    class ReadGuard:
        def call_tool(self, name, arguments, **limits):
            assert name in ALLOWED, "Global console attempted an unexpected tool"
            return client.call_tool(name, arguments, **limits)
    return ReadGuard()


async def ui(registry):
    app = PortfolioApp(registry, PortfolioSource(factory), manage=True)
    async with app.run_test(size=(120, 36)) as pilot:
        for _ in range(250):
            await pilot.pause(0.02)
            if not app.in_flight and app.result is not None:
                break
        assert [row["status"] for row in app.result["items"]] == ["ready", "ready", "unavailable"]
        assert app.query_one("#portfolio-records", DataTable).row_count == 3
        await pilot.resize_terminal(80, 24)
        assert app.query_one("#portfolio-records").region.height > 0
        app.selected_name = "second"
        app.action_open_project()
    assert app.return_value.entry.name == "second" and app.closed


def main():
    with tempfile.TemporaryDirectory(prefix="isekai-projects-http-") as temporary:
        root = Path(temporary)
        registry = ProjectRegistry(root / "connections.json")
        project = os.environ["MEMORY_TEST_PROJECT_ID"]
        entries = [ProjectEntry.parse({
            "name": name, "label": label, "endpoint": os.environ["MEMORY_BASE_URL"] + "/mcp",
            "organization_id": "synthetic", "project_id": target, "credential_ref": ref,
            "expected_actor_id": "e2e-user",
        }) for name, label, target, ref in [
            ("first", "첫 프로젝트", project, "portfolio-main"),
            ("second", "두 번째 프로젝트", project + "-other", "portfolio-other"),
            ("denied", "허용되지 않은 대상", project + "-denied", "portfolio-main"),
        ]]
        registry.save(entries, expected_digest=registry.load().digest)
        source = PortfolioSource(factory)
        result = source.fetch(entries)
        assert [row["project_id"] for row in result["items"]] == [entry.profile.project_id for entry in entries]
        assert [row["status"] for row in result["items"]] == ["ready", "ready", "unavailable"]
        assert result["items"][2]["error_code"] == "ISK-MEMORY-0005"
        assert "counts" not in result["items"][2]
        scoped = source.fetch(entries, scope="project")
        assert [row["status"] for row in scoped["items"]] == ["ready", "unavailable", "unavailable"]
        environment = {**os.environ, "PYTHONPATH": os.environ["MEMORY_CORE_SOURCE"],
                       "ISEKAI_MEMORY_CREDENTIAL_PORTFOLIO_DASH_MAIN": os.environ["MEMORY_ADMIN_TOKEN"],
                       "ISEKAI_MEMORY_CREDENTIAL_PORTFOLIO_DASH_OTHER": os.environ["MEMORY_CROSS_PROJECT_TOKEN"]}
        command = [sys.executable, "-m", "isekai.cli", "--output", "json", "watch",
                   "--connections", str(registry.path), "--once"]
        completed = subprocess.run(command, env=environment, cwd=root, capture_output=True, text=True, timeout=25)
        assert completed.returncode == 0, "Global CLI failed; raw output intentionally withheld"
        output = json.loads(completed.stdout)["result"]
        assert output["registered_projects"] == 3
        assert [row["status"] for row in output["items"]] == ["ready", "ready", "unavailable"]
        asyncio.run(ui(registry))
        assert not list(root.rglob("state.db")) and not (root / ".isekai").exists()
        assert "token" not in registry.path.read_text()
    print(json.dumps({"core_multi_project_http": True, "two_distinct_project_tokens": True,
                      "denied_target_isolated": True, "existing_admin_boundary_preserved": True,
                      "global_cli_and_tui": True, "no_server_mutation_or_local_bootstrap": True}))


if __name__ == "__main__":
    main()
