"""Real Core capture -> shared Memory -> revoked sender -> two independent receivers."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from isekai_memory.config import Settings
from isekai_memory.server.auth import hash_token
from isekai_memory.store import queries
from isekai_memory.store.database import close_pool, init_pool

sys.path.insert(0, os.environ["MEMORY_CORE_SOURCE"])

from isekai.infrastructure.errors import IsekaiError  # noqa: E402
from isekai.infrastructure.schema import SchemaRegistry  # noqa: E402
from isekai.memory.client import MemoryMcpClient  # noqa: E402
from isekai.memory.config import MemoryConfig  # noqa: E402
from isekai.memory.continuity import ContinuityClient  # noqa: E402

LOCK = "sha256:" + "b" * 64


def runtime(root, project):
    return SimpleNamespace(project_root=root, project_id=project, schemas=SchemaRegistry(),
                           active_lock_digest=lambda: LOCK, require_continuity_capability=lambda _: None,
                           continuity_path_allowed=lambda _: True)


async def revoke_sender():
    await init_pool(Settings(database_url=os.environ["MEMORY_TEST_DATABASE_URL"]))
    try:
        row = await queries.get_token_by_hash(token_hash=hash_token(os.environ["MEMORY_COLLABORATOR_TOKEN"]))
        await queries.revoke_token(token_id=str(row["id"]))
    finally:
        await close_pool()


def main():
    project = os.environ["MEMORY_TEST_PROJECT_ID"]
    config = MemoryConfig(endpoint=os.environ["MEMORY_BASE_URL"] + "/mcp", organization_id="test", credential_ref="test",
                          continuity_enabled=True, continuity_capture=True, continuity_allowed_paths=("src", "tests"))

    def client(environment_key):
        return MemoryMcpClient(config, SimpleNamespace(resolve=lambda _: os.environ[environment_key]))

    admin = client("MEMORY_ADMIN_TOKEN")

    def call(name, args):
        return admin.call_tool(name, {"project_id": project, **args})

    policy = {"enabled": True, "default_recipient_user_ids": ["e2e-user", "recipient-two"], "default_backup_user_ids": [],
              "sender_rules": [], "retention_hours": 168, "lease_seconds": 300, "checkpoint_interval_seconds": 60,
              "checkpoint_max_bytes": 1048576, "checkpoint_allowed_paths": ["src", "tests"], "allow_emergency_takeover": False}
    call("memory_continuity_policy_set", {"policy": policy, "expected_version": 0, "idempotency_key": uuid4().hex, "reason": "M8 E2E"})
    with tempfile.TemporaryDirectory(prefix="isekai-core-continuity-") as folder:
        root = Path(folder)
        sender = root / "sender"
        sender.mkdir()
        (sender / "src").mkdir()
        (sender / "src/main.py").write_text("original\n")
        (sender / ".gitignore").write_text(".isekai/\n")
        for args in (["init", "-q"], ["add", "src/main.py", ".gitignore"],
                     ["-c", "user.name=M8 Test", "-c", "user.email=m8@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"]):
            subprocess.run(["git", "-C", str(sender), *args], check=True, capture_output=True)
        (sender / "src/main.py").write_text("in-progress tracked change\n")
        (sender / "tests").mkdir()
        (sender / "tests/new.txt").write_text("previously untracked work\n")
        source = ContinuityClient(runtime(sender, project), config, client("MEMORY_COLLABORATOR_TOKEN"))
        saved = source.capture_state("work-one", "Recover interrupted work", LOCK, "In progress, no terminal Result", "internal")
        assert saved["workspace_state"] == "captured"
        # No graceful handoff or continued sender credentials are needed after the saved checkpoint.
        asyncio.run(revoke_sender())
        try:
            source.policy()
            raise AssertionError("revoked sender still authenticated")
        except IsekaiError:
            pass
        published = call("memory_continuity_publish", {"source_kind": "checkpoint", "source_id": saved["checkpoint_id"],
            "expected_policy_version": 1, "idempotency_key": uuid4().hex, "reason": "unexpected contributor departure",
            "work_units": [{"key": "implementation", "summary": "Continue implementation", "assignee_user_ids": ["e2e-user"]},
                           {"key": "verification", "summary": "Verify the saved work independently", "assignee_user_ids": ["recipient-two"]}]})
        status = call("memory_continuity_status", {"bundle_id": published["bundle_id"]})
        assert status["intake"] == {"total": 2, "acknowledged": 0}
        for index, (user, env) in enumerate((("e2e-user", "MEMORY_ADMIN_TOKEN"), ("recipient-two", "MEMORY_RECIPIENT_TOKEN"))):
            receiver = root / ("receiver-" + str(index))
            subprocess.run(["git", "clone", "--no-hardlinks", "--quiet", str(sender), str(receiver)], check=True, capture_output=True)
            service = ContinuityClient(runtime(receiver, project), config, client(env))
            delivery = next(d for d in status["deliveries"] if d["recipient_user_id"] == user)
            unit = next(u for u in status["units"] if u["assignee_user_ids"] == [user])
            assert service.inspect(delivery["id"])["automatic_resume"] is False
            claimed = service.claim(unit["id"])
            prepared = service.prepare(delivery["id"], unit["id"])
            restored = Path(prepared["workspace"])
            assert (restored / "src/main.py").read_text() == "in-progress tracked change\n"
            assert (restored / "tests/new.txt").read_text() == "previously untracked work\n"
            assert (receiver / "src/main.py").read_text() == "original\n"
            assert prepared["status"] == "prepared_requires_local_checks_and_approval"
            service.call("memory_continuity_ack", {"delivery_id": delivery["id"], "idempotency_key": uuid4().hex})
            assert call("memory_continuity_status", {"bundle_id": published["bundle_id"]})["intake"]["acknowledged"] == index + 1
            service.renew(unit["id"], claimed["lease_expires_at"], claimed["claim_generation"])
            service.release(unit["id"], "release", "handoff processing paused", claimed["claim_generation"])
            replacement = service.claim(unit["id"])
            assert replacement["claim_generation"] > claimed["claim_generation"]
            try:
                service.release(unit["id"], "complete", "stale CLI retry", claimed["claim_generation"])
                raise AssertionError("stale local generation was accepted")
            except IsekaiError:
                pass
            service.release(unit["id"], "complete", "reported local test validation", replacement["claim_generation"])
    print(json.dumps({"core_checkpoint_capture": True, "departed_sender_not_required": True, "independent_recipients": 2,
                      "tracked_and_untracked_restored": True, "isolated_preparation": True, "automatic_execution": False}))


if __name__ == "__main__":
    main()
