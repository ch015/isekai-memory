"""Real HTTP policy forms and durable reply-loss retry with synthetic project tokens."""

import asyncio
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.environ["MEMORY_CORE_SOURCE"])

from isekai.cli.console.app import WatchApp  # noqa: E402
from isekai.cli.console.model import DashboardSource, Selection  # noqa: E402
from isekai.cli.console.policy_forms import PolicyEditor, PolicyOutcome, PolicyPreview  # noqa: E402
from isekai.infrastructure.errors import IsekaiError  # noqa: E402
from isekai.memory.admin_policy import AdminPolicyClient  # noqa: E402
from isekai.memory.client import MemoryMcpClient  # noqa: E402
from isekai.memory.config import MemoryConfig  # noqa: E402
from textual.widgets import Button, Checkbox, Input, SelectionList, TextArea  # noqa: E402


class LoseReply:
    def __init__(self, client, state=None):
        self.client, self.config = client, client.config
        self.state = state if state is not None else {"lose": False, "requests": []}

    @contextmanager
    def credential_snapshot(self):
        with self.client.credential_snapshot() as scoped:
            yield LoseReply(scoped, self.state)

    def call_tool(self, name, args, **limits):
        result = self.client.call_tool(name, args, **limits)
        if name.endswith("_policy_set") or name in {"memory_continuity_publish", "memory_continuity_reassign", "memory_checkpoint_forget"}:
            self.state["requests"].append((name, dict(args), result))
            if self.state["lose"]:
                self.state["lose"] = False
                raise IsekaiError("ISK-MEMORY-0003", "synthetic response lost AFTER server commit")
        return result


async def idle(app, pilot):
    for _ in range(400):
        await pilot.pause(0.02)
        if not app.admin_busy and app.poll.in_flight is None and app.screen.is_mounted:
            await pilot.pause()
            if not app.admin_busy and app.poll.in_flight is None and app.screen.is_mounted:
                return
    raise AssertionError("admin HTTP operation exceeded the smoke budget")


async def scenario(root):
    project = os.environ["MEMORY_TEST_PROJECT_ID"]
    config = MemoryConfig(os.environ["MEMORY_BASE_URL"] + "/mcp", "synthetic", "admin")
    raw = MemoryMcpClient(config, SimpleNamespace(resolve=lambda _: os.environ["MEMORY_ADMIN_TOKEN"]))
    transport = LoseReply(raw)
    verifier = AdminPolicyClient(raw, project, "e2e-user")
    original = verifier.policy("continuity")
    app = WatchApp(DashboardSource(transport, project, actor_id="e2e-user"), manage=True,
                   selection=Selection(view="admin", scope="project"), admin_state_root=root / "pending")
    async with app.run_test(size=(80, 24)) as pilot:
        await idle(app, pilot)
        await pilot.press("c")
        await idle(app, pilot)
        assert isinstance(app.screen, PolicyEditor)
        editor = app.screen
        editor.query_one("#recipients", SelectionList).deselect_all().select("e2e-user").select("recipient-two")
        editor.query_one("#backups", SelectionList).deselect_all()
        editor.query_one("#lease-seconds", Input).value = "120"
        editor.query_one("#paths", TextArea).text = "src\ndocs"
        editor.query_one("#reason", Input).value = "synthetic TUI administrator 1:N policy"
        editor.query_one("#preview-policy", Button).press()
        await pilot.pause()
        assert not transport.state["requests"]
        app.screen.query_one("#confirm-change", Checkbox).focus()
        await pilot.press("space")
        app.screen.query_one("#send-policy", Button).focus()
        await pilot.press("enter")
        await idle(app, pilot)
        assert isinstance(app.screen, PolicyOutcome)
        after = verifier.policy("continuity")
        assert after["version"] == original["version"] + 1
        assert set(after["policy"]["default_recipient_user_ids"]) == {"e2e-user", "recipient-two"}
        assert after["policy"]["lease_seconds"] == 120
        assert after["policy"]["checkpoint_allowed_paths"] == ["src", "docs"]
        await pilot.press("escape")
        await idle(app, pilot)
        app.action_edit_presence()
        await idle(app, pilot)
        assert isinstance(app.screen, PolicyEditor)
        app.screen.query_one("#reason", Input).value = "synthetic lost policy reply"
        app.screen.query_one("#idle-after-seconds", Input).value = "600"
        app.screen.query_one("#preview-policy", Button).press()
        await pilot.pause()
        transport.state["lose"] = True
        preview = app.screen
        preview.query_one("#confirm-change", Checkbox).value = True
        await pilot.pause()
        preview.query_one("#send-policy", Button).press()
        await idle(app, pilot)
        assert app.pending_policy.load()["status"] == "pending"
        committed = verifier.policy("presence")
        assert committed["policy"]["idle_after_seconds"] == 600
        await pilot.press("escape", "escape")
        app.action_pending_policy()
        await idle(app, pilot)
        assert isinstance(app.screen, PolicyPreview) and app.screen.retry
        app.screen.query_one("#confirm-change", Checkbox).value = True
        await pilot.pause()
        app.screen.query_one("#send-policy", Button).press()
        await idle(app, pilot)
        assert isinstance(app.screen, PolicyOutcome)
        assert app.pending_policy.load()["status"] == "confirmed"
        assert verifier.policy("presence")["version"] == committed["version"]
        writes = transport.state["requests"]
        assert len(writes) == 3 and writes[-1][1] == writes[-2][1] and writes[-1][2]["replayed"]
    print(json.dumps({"admin_policy_tui_http": True, "fanout_policy": 2, "lost_reply_same_request_retry": True,
                      "no_duplicate_version": True, "real_cli_account": False}))


def main():
    with tempfile.TemporaryDirectory(prefix="isekai-admin-policy-http-") as temporary:
        asyncio.run(scenario(Path(temporary)))


if __name__ == "__main__":
    main()
