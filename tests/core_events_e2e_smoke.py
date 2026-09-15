"""Two process phases around a real HTTP server restart; only opaque cursor state persists."""
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, os.environ["MEMORY_CORE_SOURCE"])

from isekai.cli.console.app import WatchApp  # noqa: E402
from isekai.cli.console.event_state import EventCursorStore  # noqa: E402
from isekai.cli.console.model import DashboardSource, Selection  # noqa: E402
from isekai.memory.client import MemoryMcpClient  # noqa: E402
from isekai.memory.config import MemoryConfig  # noqa: E402


def connection(root):
    config = MemoryConfig(os.environ["MEMORY_BASE_URL"] + "/mcp", "synthetic", "events")
    client = MemoryMcpClient(config, SimpleNamespace(resolve=lambda _: os.environ["MEMORY_ADMIN_TOKEN"]))
    source = DashboardSource(client, os.environ["MEMORY_TEST_PROJECT_ID"], actor_id="e2e-user",
                             event_store=EventCursorStore(root / "resume"))
    return client, source


def before(root):
    client, source = connection(root)
    first = source.fetch(Selection(view="events"))
    assert source.accept_events(first)
    policy = client.call_tool("memory_continuity_policy_get", {"project_id": source.project_id})
    changed = client.call_tool("memory_continuity_policy_set", {"project_id": source.project_id,
        "policy": policy["policy"], "expected_version": policy["version"], "idempotency_key": uuid4().hex,
        "reason": "synthetic notification across server process restart"})
    (root / "expected.json").write_text(json.dumps({"version": changed["version"]}))
    cursor = next((root / "resume").glob("*.json"))
    assert set(json.loads(cursor.read_text())) == {"schema_version", "binding", "cursor"}


async def after(root):
    _, source = connection(root)
    expected = json.loads((root / "expected.json").read_text())["version"]
    app = WatchApp(source, selection=Selection(view="events"))
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(500):
            await pilot.pause(0.01)
            if app.poll.in_flight is None:
                break
        assert app.poll.snapshot, app.poll.error_code
        data = app.poll.snapshot["events"]["batch"]
        assert not data["reset_required"]
        assert any(row["topic"] == "policy_changed" and row["revision"] == expected for row in app.row_values.values())
    cursor = next((root / "resume").glob("*.json"))
    saved = json.loads(cursor.read_text())
    saved["cursor"] = "synthetic-corrupt-cursor"
    cursor.write_text(json.dumps(saved))
    _, recovering = connection(root)
    fresh = recovering.fetch(Selection())
    assert fresh["events"]["batch"]["reset_reason"] == "cursor_unusable"
    assert fresh["events"]["batch"]["items"] == [] and fresh["overview"]["actor_id"] == "e2e-user"
    assert recovering.accept_events(fresh)
    print(json.dumps({"durable_events_server_restart_http_tui": True, "opaque_cursor_only": True,
                      "corrupt_cursor_full_refresh": True, "no_work_mutation_by_observation": True}))


if __name__ == "__main__":
    root = Path(sys.argv[2])
    if sys.argv[1] == "before":
        before(root)
    else:
        asyncio.run(after(root))
