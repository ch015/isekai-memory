"""Usage policy forms and read-only totals over real HTTP with synthetic reports."""
import asyncio
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, os.environ["MEMORY_CORE_SOURCE"])

from core_admin_policy_e2e_smoke import LoseReply, idle  # noqa: E402
from isekai.cli.console.app import WatchApp  # noqa: E402
from isekai.cli.console.model import DashboardSource, Selection  # noqa: E402
from isekai.cli.console.policy_forms import PolicyEditor, PolicyOutcome, PolicyPreview  # noqa: E402
from isekai.cli.console.usage_forms import UsageFilters  # noqa: E402
from isekai.host.usage import collect_usage  # noqa: E402
from isekai.memory.admin_policy import AdminPolicyClient  # noqa: E402
from isekai.memory.client import MemoryMcpClient  # noqa: E402
from isekai.memory.config import MemoryConfig  # noqa: E402
from isekai.memory.usage import UsageSession, drain  # noqa: E402
from isekai.memory.usage_schema import FIELDS  # noqa: E402
from textual.widgets import Button, Checkbox, Input, Select, Static  # noqa: E402


def client(token):
    return MemoryMcpClient(MemoryConfig(os.environ["MEMORY_BASE_URL"] + "/mcp", "synthetic", "test"),
                           SimpleNamespace(resolve=lambda _: os.environ[token]))


def synthetic_report(raw, project, total):
    args = {"project_id": project, "execution_attempt_id": str(uuid4()), "meter_epoch": str(uuid4()),
            "session_token": secrets.token_urlsafe(32), "host_kind": "codex", "host_version": "synthetic",
            "adapter_version": "test-v1", "provider": "unknown", "model_id": "fixture-model", "classification": "internal",
            "observation_scope": "exclusive_run", "parent_session_id": None, "work_binding": None}
    registered = raw.call_tool("memory_usage_register", args)
    metrics = {key: {"value": None, "quality": "unavailable", "estimate_method": None,
                     "omission_reason": "not_reported"} for key in FIELDS}
    metrics["total_tokens"] = {"value": total, "quality": "reported", "estimate_method": None, "omission_reason": None}
    report = {"project_id": project, "session_id": registered["session_id"], "session_token": args["session_token"],
              "sequence": 1, "semantics_version": 1, "metrics": metrics, "completion_state": "final",
              "coverage": "complete", "source_occurred_at": None}
    raw.call_tool("memory_usage_report", report)
    assert raw.call_tool("memory_usage_report", report)["replayed"]


async def scenario(root):
    project = os.environ["MEMORY_TEST_PROJECT_ID"]
    admin, recipient = client("MEMORY_ADMIN_TOKEN"), client("MEMORY_RECIPIENT_TOKEN")
    transport = LoseReply(admin)
    app = WatchApp(DashboardSource(transport, project, actor_id="e2e-user"), manage=True,
                   selection=Selection(view="admin", scope="project"), admin_state_root=root / "pending")
    async with app.run_test(size=(80, 24)) as pilot:
        await idle(app, pilot)
        await pilot.press("j")
        await idle(app, pilot)
        assert isinstance(app.screen, PolicyEditor) and app.screen.kind == "usage"
        app.screen.query_one("#enabled", Checkbox).value = True
        app.screen.query_one("#usage-policy-timezone", Input).value = "Asia/Seoul"
        app.screen.query_one("#project-alert-tokens", Input).value = "150"
        app.screen.query_one("#user-alert-tokens", Input).value = "80"
        app.screen.query_one("#reason", Input).value = "Synthetic usage policy validation"
        app.screen.query_one("#preview-policy", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, PolicyPreview) and not transport.state["requests"]
        transport.state["lose"] = True
        app.screen.query_one("#confirm-change", Checkbox).value = True
        await pilot.pause()
        app.screen.query_one("#send-policy", Button).press()
        await idle(app, pilot)
        assert app.pending_policy.load()["status"] == "pending"
        await pilot.press("escape", "escape")
        await idle(app, pilot)
        app.action_pending_policy()
        await idle(app, pilot)
        assert isinstance(app.screen, PolicyPreview) and app.screen.retry
        app.screen.query_one("#confirm-change", Checkbox).value = True
        await pilot.pause()
        app.screen.query_one("#send-policy", Button).press()
        await idle(app, pilot)
        assert isinstance(app.screen, PolicyOutcome)
        assert transport.state["requests"][-1][1] == transport.state["requests"][-2][1]
        assert transport.state["requests"][-1][2]["replayed"]
    assert AdminPolicyClient(admin, project, "e2e-user").policy("usage")["policy"]["enabled"]
    synthetic_report(admin, project, 100)
    synthetic_report(recipient, project, 60)
    class LostReportReply(LoseReply):
        def call_tool(self, name, args, **limits):
            value = super().call_tool(name, args, **limits)
            if name == "memory_usage_report" and not self.state.get("report_lost"):
                self.state["report_lost"] = True
                raise IsekaiError("ISK-MEMORY-0003", "synthetic lost usage receipt")
            return value
        def credential_snapshot(self):
            from contextlib import nullcontext
            return nullcontext(self)
    from isekai.infrastructure.errors import IsekaiError

    reporter_transport = LostReportReply(client("MEMORY_RECIPIENT_THREE_TOKEN"))
    reporter = UsageSession(root, reporter_transport, project, str(uuid4()), "internal", "codex", "0.154.0", "1.0.0")
    reporter.start()
    raw_usage = b'{"type":"thread.started"}\n{"type":"turn.started"}\n{"type":"turn.completed","usage":{"input_tokens":20,"output_tokens":0}}'
    reporter.finish(collect_usage("codex", "0.154.0", "1.0.0", raw_usage).as_dict())
    assert reporter.queue.paths() and reporter_transport.state["report_lost"]
    assert drain(reporter_transport, reporter.queue)["confirmed"] == 1
    assert not reporter.queue.paths()
    for raw, actor, scope, expected in ((admin, "e2e-user", "project", 180), (recipient, "recipient-two", "mine", 60)):
        app = WatchApp(DashboardSource(raw, project, actor_id=actor), selection=Selection(view="usage", scope=scope))
        async with app.run_test(size=(80, 24)) as pilot:
            await idle(app, pilot)
            assert app.poll.snapshot is not None, app.poll.error_code
            page = app.poll.snapshot["page"]
            assert page["summary"]["reported"]["total_tokens"]["value"] == expected
            assert page["summary"]["reported"]["input_total_tokens"]["value"] == (20 if scope == "project" else None)
            assert page["period"]["timezone"] == "Asia/Seoul"
            assert len(page["alerts"]) == (2 if scope == "project" else 0)
            assert "Core 밖" in str(app.query_one("#notice", Static).content)
            await pilot.press("f")
            await pilot.pause()
            assert isinstance(app.screen, UsageFilters)
            app.screen.query_one("#usage-group-by", Select).value = "user"
            app.screen.query_one("#usage-filter-apply", Button).press()
            await idle(app, pilot)
            assert app.poll.snapshot["page"]["group_by"] == "user"
            assert app.poll.snapshot["page"]["summary"]["reported"]["total_tokens"]["value"] == expected
            assert app.usage_new_alerts == 0  # same levels were already displayed before the filter form
            app.action_refresh()
            await idle(app, pilot)
            assert app.usage_new_alerts == 0
            await pilot.press("d")
            await idle(app, pilot)
            assert app.poll.snapshot is not None, app.poll.error_code
            assert app.poll.selection.usage_mode == "runs"
            runs = app.poll.snapshot["page"]["items"]
            assert len(runs) == (3 if scope == "project" else 1)
            assert sum(row["metrics"]["total_tokens"]["value"] for row in runs) == expected
            assert all(row["actor_id"] == actor for row in runs) if scope == "mine" else True
            assert app.query_one("#usage-alerts").has_class("hidden")
            await pilot.press("d")
            await idle(app, pilot)
            assert app.usage_new_alerts == 0
            await pilot.resize_terminal(120, 36)
            await pilot.pause()
            assert not app.query_one("#inline-detail").has_class("hidden")
    print(json.dumps({"usage_http_tui": True, "schema_revision": "013", "admin_policy_lost_reply_retry": True,
                      "own_and_project_totals": [60, 180], "replay_not_double_counted": True,
                      "parser_reporter_outbox_http": True, "per_run_listing": True, "alert_repeat_suppressed": True, "real_cli_account": False}))


def main():
    with tempfile.TemporaryDirectory(prefix="isekai-usage-http-") as temporary:
        asyncio.run(scenario(Path(temporary)))


if __name__ == "__main__":
    main()
