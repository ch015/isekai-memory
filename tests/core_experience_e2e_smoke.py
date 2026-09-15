"""Real HTTP experience queue/review/search UI; synthetic source and no model account execution."""
import asyncio
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, os.environ["MEMORY_CORE_SOURCE"])

from core_admin_policy_e2e_smoke import idle  # noqa: E402
from isekai.cli.console.action_forms import ActionPreview  # noqa: E402
from isekai.cli.console.app import WatchApp  # noqa: E402
from isekai.cli.console.experience_forms import ExperienceBrowser, ExperienceDetail  # noqa: E402
from isekai.cli.console.model import DashboardSource, Selection  # noqa: E402
from isekai.cli.console.policy_forms import PolicyOutcome  # noqa: E402
from isekai.cli.console.review import ReviewPages  # noqa: E402
from isekai.infrastructure.errors import IsekaiError  # noqa: E402
from isekai.memory.client import MemoryMcpClient  # noqa: E402
from isekai.memory.config import MemoryConfig  # noqa: E402
from textual.widgets import Button, Checkbox, DataTable, Input  # noqa: E402


class LoseReview:
    def __init__(self, client, state=None):
        self.client, self.config = client, client.config
        self.state = state if state is not None else {"lose": True, "requests": [], "metadata": []}

    @contextmanager
    def credential_snapshot(self):
        with self.client.credential_snapshot() as scoped:
            yield LoseReview(scoped, self.state)

    def call_tool(self, name, args, **limits):
        result = self.client.call_tool(name, args, **limits)
        if name == "memory_experience_list" and args.get("metadata_only"):
            assert all(not {"content", "source", "tags"} & set(row) for row in result["items"])
            self.state["metadata"].append(True)
        if name == "memory_experience_review":
            self.state["requests"].append((dict(args), result))
            if self.state["lose"]:
                self.state["lose"] = False
                raise IsekaiError("ISK-MEMORY-0003", "Synthetic lost experience review receipt")
        return result


async def scenario(root):
    project = os.environ["MEMORY_TEST_PROJECT_ID"]
    config = MemoryConfig(os.environ["MEMORY_BASE_URL"] + "/mcp", "synthetic", "test")
    admin = MemoryMcpClient(config, SimpleNamespace(resolve=lambda _: os.environ["MEMORY_ADMIN_TOKEN"]))
    user = MemoryMcpClient(config, SimpleNamespace(resolve=lambda _: os.environ["MEMORY_RECIPIENT_TOKEN"]))
    source = admin.call_tool("memory_experience_list", {"project_id": project, "status": "superseded"})["items"][0]
    query = "consolememory" + uuid4().hex
    proposed = admin.call_tool("memory_experience_propose", {
        "project_id": project, "source_handoff_id": source["source_handoff_id"], "idempotency_key": uuid4().hex,
        "kind": "lesson", "title": query, "content": query + " 합성 전체 내용 검토 " + "검토 "*900 + "END-MARKER",
    })
    target = proposed["memory_id"]
    transport = LoseReview(admin)
    app = WatchApp(DashboardSource(transport, project, actor_id="e2e-user"), manage=True,
                   selection=Selection(view="memory"), admin_state_root=root / "pending")
    async with app.run_test(size=(80, 24)) as pilot:
        await idle(app, pilot)
        await pilot.press("v")
        await idle(app, pilot)
        assert isinstance(app.screen, ExperienceBrowser)
        table = app.screen.query_one("#experience-records", DataTable)
        assert target in app.screen.values
        table.move_cursor(row=table.get_row_index(target))
        table.focus()
        await pilot.press("enter")
        await idle(app, pilot)
        assert isinstance(app.screen, ExperienceDetail)
        pages = app.screen.query_one(ReviewPages)
        assert "END-MARKER" in "".join(pages.pages)
        while not pages.complete:
            pages.query_one("#review-next", Button).press()
            await pilot.pause()
        app.screen.query_one("#experience-approve", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, ActionPreview)
        app.screen.query_one("#confirm-action", Checkbox).value = True
        await pilot.pause()
        app.screen.query_one("#send-action", Button).press()
        await idle(app, pilot)
        assert app.pending_policy.load()["status"] == "pending"
        assert "END-MARKER" not in app.pending_policy.path.read_text()
        while len(app.screen_stack) > 1:
            await pilot.press("escape")
        await idle(app, pilot)
        app.action_pending_policy()
        await idle(app, pilot)
        assert isinstance(app.screen, ActionPreview) and app.screen.retry
        app.screen.query_one("#confirm-action", Checkbox).value = True
        await pilot.pause()
        app.screen.query_one("#send-action", Button).press()
        await idle(app, pilot)
        assert isinstance(app.screen, PolicyOutcome)
        assert transport.state["requests"][0][0] == transport.state["requests"][1][0]
        assert transport.state["requests"][1][1]["already_applied"] and transport.state["metadata"]
    app = WatchApp(DashboardSource(user, project, actor_id="recipient-two"), selection=Selection(view="memory"))
    async with app.run_test(size=(120, 36)) as pilot:
        await idle(app, pilot)
        await pilot.press("k")
        await idle(app, pilot)
        assert isinstance(app.screen, ExperienceBrowser) and not app.screen.review
        app.screen.query_one("#experience-query", Input).value = query
        app.screen.query_one("#experience-search", Button).press()
        await idle(app, pilot)
        assert target in app.screen.values
        app.screen.query_one("#experience-records", DataTable).focus()
        await pilot.press("enter")
        await idle(app, pilot)
        assert isinstance(app.screen, ExperienceDetail) and not app.screen.review
        assert "END-MARKER" in "".join(app.screen.query_one(ReviewPages).pages)
    print(json.dumps({"experience_tui_http": True, "metadata_only_review_queue": True,
                      "full_body_explicit_review": True, "lost_reply_exact_version_retry": True,
                      "different_user_search_and_citation_read": True, "real_cli_account": False}))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="m9-experience-http-") as temporary:
        asyncio.run(scenario(Path(temporary)))
