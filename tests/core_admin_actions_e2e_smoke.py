"""Admin TUI -> real HTTP -> PostgreSQL, synthetic sources and actors only."""

import asyncio
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.environ["MEMORY_CORE_SOURCE"])

from core_admin_policy_e2e_smoke import LoseReply, idle  # noqa: E402
from isekai.cli.console.action_forms import (  # noqa: E402
    ActionPreview,
    AssignmentEditor,
    AuditScreen,
    ForgetEditor,
    WorkEditor,
)
from isekai.cli.console.app import WatchApp  # noqa: E402
from isekai.cli.console.model import DashboardSource, Selection  # noqa: E402
from isekai.cli.console.policy_forms import PolicyOutcome  # noqa: E402
from isekai.cli.console.review import ReviewPages  # noqa: E402
from isekai.memory.admin_actions import AdminActionClient  # noqa: E402
from isekai.memory.admin_policy import AdminPolicyClient  # noqa: E402
from isekai.memory.client import MemoryMcpClient  # noqa: E402
from isekai.memory.config import MemoryConfig  # noqa: E402
from textual.widgets import Button, Checkbox, Input, SelectionList, Tabs  # noqa: E402


async def reviewed(screen, pilot):
    pages = screen.query_one(ReviewPages)
    for index in range(len(pages.pages)):
        pages.index = index
        pages.draw()
    await pilot.pause()
    screen.query_one("#confirm-action", Checkbox).focus()
    await pilot.press("space")
    screen.query_one("#send-action", Button).focus()
    await pilot.press("enter")


async def scenario(root):
    project = os.environ["MEMORY_TEST_PROJECT_ID"]
    config = MemoryConfig(os.environ["MEMORY_BASE_URL"] + "/mcp", "synthetic", "admin")
    raw = MemoryMcpClient(config, SimpleNamespace(resolve=lambda _: os.environ["MEMORY_ADMIN_TOKEN"]))
    recipient = MemoryMcpClient(config, SimpleNamespace(resolve=lambda _: os.environ["MEMORY_RECIPIENT_TOKEN"]))
    verifier = AdminActionClient(raw, project, "e2e-user")
    policy_client = AdminPolicyClient(raw, project, "e2e-user")
    policy = policy_client.policy("continuity")
    configured = {**policy["policy"], "default_recipient_user_ids": ["recipient-two", "recipient-three"],
                  "allow_emergency_takeover": True}
    policy_client.apply(policy_client.plan("continuity", policy["version"], configured, "synthetic admin workflow fixture"))
    # Metadata-only clean synthetic checkpoint; this never reads or captures a local checkout.
    package = {"schema_version": 1, "goal": "Synthetic admin recovery acceptance",
               "verified_state": "Fixture only, not real execution", "repository": {"source_id": "synthetic", "commit": "a" * 40},
               "workspace": {"state": "clean"}, "artifacts": [], "remaining_work": ["Verify locally before any execution"],
               "next_steps": ["Review synthetic checkpoint"], "blockers": []}
    saved = raw.call_tool("memory_checkpoint_save", {"project_id": project, "work_id": "admin-tui-synthetic",
        "expected_version": 0, "continuation": package, "classification": "internal",
        "lock_snapshot_digest": "sha256:" + "a" * 64, "idempotency_key": secrets.token_hex(16)})
    checkpoint_id = saved["checkpoint_id"]
    transport = LoseReply(raw)
    app = WatchApp(DashboardSource(transport, project, actor_id="e2e-user"), manage=True,
                   selection=Selection(view="checkpoints", scope="project"), admin_state_root=root / "pending")
    async with app.run_test(size=(80, 24)) as pilot:
        await idle(app, pilot)
        assert checkpoint_id in app.row_values
        app.selected_key = checkpoint_id
        app.action_publish_checkpoint()
        await idle(app, pilot)
        assert isinstance(app.screen, AssignmentEditor)
        app.screen.query_one("#assignment-reason", Input).value = "synthetic two-recipient recovery"
        app.screen.query_one("#preview-assignment", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, ActionPreview)
        transport.state["lose"] = True
        await reviewed(app.screen, pilot)
        await idle(app, pilot)
        assert app.pending_policy.load()["status"] == "pending"
        bundle_id = transport.state["requests"][-1][2]["bundle_id"]
        before = verifier.status(bundle_id)
        assert before["intake"] == {"total": 2, "acknowledged": 0}
        await pilot.press("escape", "escape")
        app.action_pending_policy()
        await idle(app, pilot)
        await reviewed(app.screen, pilot)
        await idle(app, pilot)
        assert isinstance(app.screen, PolicyOutcome)
        assert transport.state["requests"][-1][1] == transport.state["requests"][-2][1]
        assert transport.state["requests"][-1][2]["replayed"]
        await pilot.press("escape")
        await idle(app, pilot)
        unit_id = before["units"][0]["id"]
        claim = recipient.call_tool("memory_continuity_claim", {"project_id": project,
                                    "unit_id": unit_id, "claim_token": secrets.token_urlsafe(32)})
        assert claim["claim_generation"] == 1
        app.query_one("#views", Tabs).active = "view-sent"
        await idle(app, pilot)
        app.selected_key = bundle_id
        app.action_reassign_bundle()
        await idle(app, pilot)
        editor = app.screen
        assert isinstance(editor, AssignmentEditor)
        editor.selected_unit = 0
        editor.query_one("#edit-unit", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, WorkEditor)
        app.screen.query_one("#work-assignees", SelectionList).deselect_all().select("recipient-three")
        app.screen.query_one("#save-unit", Button).press()
        await pilot.pause()
        editor.query_one("#takeover-enabled", Checkbox).value = True
        editor.query_one("#takeover-units", SelectionList).select("continue")
        editor.query_one("#confirm-running", Checkbox).value = True
        editor.query_one("#assignment-reason", Input).value = "synthetic explicit emergency reassignment"
        editor.query_one("#preview-assignment", Button).press()
        await pilot.pause()
        await reviewed(app.screen, pilot)
        await idle(app, pilot)
        assert isinstance(app.screen, PolicyOutcome)
        after = verifier.status(bundle_id)
        assert after["bundle"]["version"] == 2 and after["units"][0]["claim_generation"] == 2
        assert after["units"][0]["claimed_by"] is None and after["units"][0]["assignee_user_ids"] == ["recipient-three"]
        assert not transport.state["requests"][-1][2]["running_processes_stopped"]
        await pilot.press("escape")
        await idle(app, pilot)
        app.action_audit_history()
        await idle(app, pilot)
        assert isinstance(app.screen, AuditScreen)
        assert app.screen.page["items"][0]["action"] == "reassign"
        await pilot.press("escape")
        app.query_one("#views", Tabs).active = "view-checkpoints"
        await idle(app, pilot)
        app.selected_key = checkpoint_id
        app.action_forget_checkpoint()
        await pilot.pause()
        assert isinstance(app.screen, ForgetEditor)
        app.screen.query_one("#forget-reason", Input).value = "erase only synthetic acceptance checkpoint"
        app.screen.query_one("#preview-forget", Button).press()
        await pilot.pause()
        app.screen.query_one("#confirm-target", Input).value = checkpoint_id
        await reviewed(app.screen, pilot)
        await idle(app, pilot)
        assert isinstance(app.screen, PolicyOutcome)
        erased = verifier.status(bundle_id)
        assert erased["bundle"]["revoked_at"] is not None
        assert all(item["revoked_at"] is not None for item in erased["deliveries"])
        assert erased["units"][0]["state"] == "cancelled" and erased["units"][0]["claim_generation"] == 3
        assert app.pending_policy.load()["status"] == "confirmed"
    print(json.dumps({"admin_actions_tui_http": True, "fanout": 2, "lost_publish_reply_exact_retry": True,
                      "emergency_generations": [1, 2, 3], "erasure_revoked_dependents": True,
                      "no_local_restore_or_execution": True, "real_cli_account": False}))


def main():
    with tempfile.TemporaryDirectory(prefix="isekai-admin-actions-http-") as temporary:
        asyncio.run(scenario(Path(temporary)))


if __name__ == "__main__":
    main()
