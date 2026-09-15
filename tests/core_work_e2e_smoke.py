"""Synthetic HTTP: two independent user workbenches, Textual confirmation and an isolated lease keeper."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, os.environ["MEMORY_CORE_SOURCE"])

from isekai.cli.console.app import WatchApp  # noqa: E402
from isekai.cli.console.model import DashboardSource, Selection  # noqa: E402
from isekai.cli.console.profile import ConnectionProfile  # noqa: E402
from isekai.cli.console.review import ReviewPages  # noqa: E402
from isekai.cli.console.work_forms import WorkOutcome, WorkPreview  # noqa: E402
from isekai.cli.console.workbench import Workbench  # noqa: E402
from isekai.infrastructure.errors import IsekaiError  # noqa: E402
from isekai.infrastructure.schema import SchemaRegistry  # noqa: E402
from isekai.memory.client import MemoryMcpClient  # noqa: E402
from isekai.memory.continuity import ContinuityClient  # noqa: E402
from isekai.memory.work_session import LeaseKeeper  # noqa: E402
from textual.widgets import Button, Checkbox  # noqa: E402

LOCK = "sha256:" + "b" * 64


def configured(root, project, token_env):
    body = {"project_id": project, "credential_refs": ["test"], "integrations": {"memory": {
        "enabled": True, "endpoint": os.environ["MEMORY_BASE_URL"] + "/mcp", "organization_id": "test", "credential_ref": "test",
        "continuity_enabled": True, "continuity_capture": True, "continuity_allowed_paths": ["src"]}}}
    (root / ".isekai").mkdir(exist_ok=True)
    (root / ".isekai/project.json").write_text(json.dumps(body))
    (root / ".isekai/active.json").write_text(json.dumps({"lock_digest": LOCK}))
    profile = ConnectionProfile.load(root)
    client = MemoryMcpClient(profile.memory, SimpleNamespace(resolve=lambda _: os.environ[token_env]))
    runtime = SimpleNamespace(project_root=root, project_id=project, config=body, schemas=SchemaRegistry(),
                              active_lock_digest=lambda: LOCK, require_continuity_capability=lambda _: None,
                              continuity_path_allowed=lambda _: True)
    def factory(_):
        return SimpleNamespace(project_id=project, config=body, runtime=runtime,
                               active_lock_digest=lambda: LOCK, close=lambda: None)
    return profile, client, runtime, factory


async def ui_ack(bench, delivery):
    app = WatchApp(DashboardSource(bench.client, bench.profile.project_id), workbench=bench, selection=Selection(view="inbox"))
    async with app.run_test(size=(80, 24)) as pilot:
        async def idle():
            for _ in range(500):
                await pilot.pause(0.01)
                if not app.admin_busy and app.poll.in_flight is None:
                    return
            raise AssertionError("HTTP console did not settle")
        await idle()
        app.work_preview("ack", {"delivery_id": delivery})
        await pilot.pause()
        assert isinstance(app.screen, WorkPreview)
        pages = app.screen.query_one(ReviewPages)
        while not pages.complete:
            pages.query_one("#review-next", Button).press()
            await pilot.pause()
        app.screen.query_one("#work-confirm", Checkbox).focus()
        await pilot.press("space")
        app.screen.query_one("#work-send", Button).focus()
        await pilot.press("enter")
        await idle()
        assert isinstance(app.screen, WorkOutcome)


def main():
    project = os.environ["MEMORY_TEST_PROJECT_ID"]
    with tempfile.TemporaryDirectory(prefix="isekai-m9-user-work-") as folder:
        root = Path(folder)
        sender = root / "sender"
        sender.mkdir()
        (sender / "src").mkdir()
        (sender / "src/main.py").write_text("base\n")
        (sender / ".gitignore").write_text(".isekai/\n")
        for args in (["init", "-q"], ["add", "src/main.py", ".gitignore"],
                     ["-c", "user.name=M9 Test", "-c", "user.email=m9@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"]):
            subprocess.run(["git", "-C", str(sender), *args], check=True, capture_output=True)
        profile, source, runtime, _ = configured(sender, project, "MEMORY_RECIPIENT_THREE_TOKEN")
        admin = MemoryMcpClient(profile.memory, SimpleNamespace(resolve=lambda _: os.environ["MEMORY_ADMIN_TOKEN"]))
        def call(name, args):
            return admin.call_tool(name, {"project_id": project, **args})
        current = call("memory_continuity_policy_get", {})
        policy = {**current["policy"], "enabled": True, "default_recipient_user_ids": ["e2e-user", "recipient-two"],
                  "default_backup_user_ids": [], "sender_rules": [], "checkpoint_allowed_paths": ["src"], "lease_seconds": 300}
        changed = call("memory_continuity_policy_set", {"policy": policy, "expected_version": current["version"],
                       "idempotency_key": uuid4().hex, "reason": "synthetic M9 user work"})
        (sender / "src/main.py").write_text("shared continuation\n")
        session, request = str(uuid4()), str(uuid4())
        capture = ContinuityClient(runtime, profile.memory, source, expected_actor="recipient-three", work_session_id=session)
        saved = capture.capture_state("m9-user-work", "Continue independently", LOCK, "synthetic", "internal", request_id=request)
        assert capture.capture_state("m9-user-work", "Continue independently", LOCK, "synthetic", "internal", request_id=request)["checkpoint_id"] == saved["checkpoint_id"]
        publisher = Workbench(profile, source, work_session_id=session)
        publisher.connect("recipient-three")
        plan = publisher.plan("publish", {"source_kind": "checkpoint", "source_id": saved["checkpoint_id"],
            "expected_policy_version": changed["version"], "recipient_user_ids": ["e2e-user", "recipient-two"],
            "work_units": [{"key": "work-" + str(index), "summary": "Separate continuation", "assignee_user_ids": [actor]}
                           for index, actor in enumerate(("e2e-user", "recipient-two"))],
            "reason": "independent user handover", "max_classification": "internal"})
        published = publisher.submit(plan, confirmed=True)["receipt"]
        for index, (actor, environment) in enumerate((("e2e-user", "MEMORY_ADMIN_TOKEN"), ("recipient-two", "MEMORY_RECIPIENT_TOKEN"))):
            receiver = root / ("receiver-" + str(index))
            subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(sender), str(receiver)], check=True, capture_output=True)
            receiver_profile, client, _, factory = configured(receiver, project, environment)
            bench = Workbench(receiver_profile, client, kernel_factory=factory)
            user = bench.connect(actor)
            status = user.status(published["bundle_id"])
            delivery = next(row for row in status["deliveries"] if row["recipient_user_id"] == actor)
            unit = next(row for row in status["units"] if row["assignee_user_ids"] == [actor])
            asyncio.run(ui_ack(bench, delivery["id"]))
            assert call("memory_continuity_status", {"bundle_id": published["bundle_id"]})["intake"]["acknowledged"] == index + 1
            claim = bench.plan("claim", {"unit_id": unit["id"], "expected_generation": unit["claim_generation"],
                                       "expected_routing_version": status["bundle"]["version"]})
            class Lost:
                config = client.config
                delegate = client
                once = True
                def credential_snapshot(self):
                    return nullcontext(self)
                def call_tool(self, name, args, **limits):
                    result = self.delegate.call_tool(name, args, **limits)
                    if name == "memory_continuity_claim" and self.once:
                        self.once = False
                        raise IsekaiError("ISK-MEMORY-0003", "synthetic lost claim response")
                    return result
            bench.client = Lost()
            try:
                bench.submit(claim, confirmed=True)
                raise AssertionError("expected dropped reply")
            except IsekaiError as error:
                assert error.code == "ISK-MEMORY-0003"
            bench.client = client
            owned = bench.submit(bench.pending()["plan"], confirmed=True)["receipt"]
            keeper = LeaseKeeper(receiver, project, receiver_profile.memory, client, bench.session, unit["id"],
                                 owned["claim_generation"], expected_actor=actor)
            assert keeper.step()
            prepare = bench.plan("prepare", {"unit_id": unit["id"], "delivery_id": delivery["id"], "max_classification": "internal"})
            prepared = bench.submit(prepare, confirmed=True)["receipt"]
            assert bench.submit(prepare, confirmed=True)["receipt"]["workspace"] == prepared["workspace"]
            assert (Path(prepared["workspace"]) / "src/main.py").read_text() == "shared continuation\n"
            assert (receiver / "src/main.py").read_text() == "base\n"
            keeper.request_stop()
            assert not keeper.step() and keeper.state == "stopped"
            released = bench.submit(bench.plan("release", {"unit_id": unit["id"], "claim_generation": owned["claim_generation"],
                                    "action": "complete", "reason": "synthetic isolated validation"}), confirmed=True)["receipt"]
            assert released["state"] == "completed" and released["execution_verified"] is False
        print(json.dumps({"user_work_tui_ack_http": True, "independent_receivers": 2, "repeatable_capture_prepare": True,
                          "lost_claim_reply_same_generation": True, "independent_keeper_http": True, "automatic_worker_execution": False}))


if __name__ == "__main__":
    main()
