"""Real Core observer -> Memory HTTP using synthetic reports, not a real CLI account."""

import json
import os
import sys
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, os.environ["MEMORY_CORE_SOURCE"])

from isekai.memory.client import MemoryMcpClient  # noqa: E402
from isekai.memory.config import MemoryConfig  # noqa: E402
from isekai.memory.presence import PresenceReporter  # noqa: E402
from isekai.memory.presence_read import PresenceClient  # noqa: E402


def controller_lifecycle(admin, receiver, project, reader):
    import tempfile
    from pathlib import Path

    from isekai.memory.controller_presence import ControllerObserver
    from isekai.memory.presence import worker_observer

    class ManualReporter(PresenceReporter):
        def start(self):
            pass

    current_token = [os.environ["MEMORY_ADMIN_TOKEN"]]
    rotating = MemoryMcpClient(admin.config, SimpleNamespace(resolve=lambda _: current_token[0]))
    with tempfile.TemporaryDirectory(prefix="m9-controller-http-") as temporary:
        runtime = SimpleNamespace(project_root=Path(temporary), project_id=project)
        config = MemoryConfig(admin.config.endpoint, "test", "test", presence_enabled=True)
        controller = ControllerObserver(runtime, config, rotating, "codex", reporter_factory=ManualReporter)
        try:
            assert controller.reporter.tick()
            parent_id = controller.parent_binding["parent_session_id"]
            def worker_call():
                assert controller.reporter.tick()
                with worker_observer(runtime, config, admin, SimpleNamespace(id="synthetic-unit"),
                                     "internal", "codex", parent_binding=controller.parent_binding) as worker:
                    assert worker.tick()
                    rows = reader.listing()["items"]
                    parent = next(row for row in rows if row["id"] == parent_id)
                    child = next(row for row in rows if row["id"] != parent_id)
                    assert parent["reported_state"] == child["reported_state"] == "running"
                    assert child["parent_session_id"] == parent_id and child["session_kind"] == "worker"
                return {}
            controller.perform("run", {}, worker_call)
            assert controller.reporter.tick()
            assert reader.listing()["items"][0]["reported_state"] == "idle"
            from datetime import UTC, datetime, timedelta
            controller.perform("action", {}, lambda: {"status": "WAITING_GATE", "gate_id": "synthetic-gate",
                               "expires_at": (datetime.now(UTC)+timedelta(minutes=1)).isoformat()})
            assert controller.reporter.tick()
            assert reader.listing("users")["items"][0]["effective_state"] == "waiting_approval"
            controller.perform("approve", {"gate_id": "synthetic-gate"}, lambda: {"state": "APPROVED"})
            assert controller.reporter.tick()
            before = reader.listing()["items"][0]["sequence"]
            current_token[0] = os.environ["MEMORY_RECIPIENT_TOKEN"]
            assert not controller.reporter.tick()
            assert reader.listing()["items"][0]["sequence"] == before
            assert PresenceClient(receiver, project).listing()["items"] == []
        finally:
            current_token[0] = os.environ["MEMORY_ADMIN_TOKEN"]
            controller.stop()
    assert reader.listing()["items"] == []


def main():
    project = os.environ["MEMORY_TEST_PROJECT_ID"]
    config = MemoryConfig(os.environ["MEMORY_BASE_URL"] + "/mcp", "test", "test")
    admin = MemoryMcpClient(config, SimpleNamespace(resolve=lambda _: os.environ["MEMORY_ADMIN_TOKEN"]))
    receiver = MemoryMcpClient(config, SimpleNamespace(resolve=lambda _: os.environ["MEMORY_RECIPIENT_TOKEN"]))

    def call(name, args=None):
        return admin.call_tool(name, {"project_id": project, **(args or {})})

    reader = PresenceClient(admin, project, actor_id="e2e-user")
    current = reader.policy()
    call("memory_presence_policy_set", {"expected_version": current["policy_version"], "idempotency_key": uuid4().hex,
         "reason": "synthetic Core observer smoke", "policy": {**current["policy"], "enabled": True}})
    first = PresenceReporter(admin, project, enabled=True, host_kind="codex", session_kind="controller")
    second = PresenceReporter(receiver, project, enabled=True, host_kind="kiro", session_kind="worker")
    try:
        first.update("idle")
        second.update("running", active_work_count=1)
        assert first.tick() and second.tick(), (first.status, second.status)
        users = reader.listing("users", scope="project")["items"]
        states = {row["user_id"]: row["effective_state"] for row in users}
        assert states == {"e2e-user": "waiting", "recipient-two": "running"}, states
        sessions = reader.listing(scope="project")["items"]
        assert len(sessions) == 2 and {row["host_kind"] for row in sessions} == {"codex", "kiro"}
        first.update("waiting_approval")
        assert first.tick()
        mine = reader.listing("users")["items"][0]
        assert mine["effective_state"] == "waiting_approval" and mine["idle_seconds"] is None
        assert all("session_token_digest" not in row for row in sessions)
    finally:
        first.stop()
        second.stop()
    assert first.status["status"] == second.status["status"] == "ended"
    assert reader.listing(scope="project")["items"] == []
    assert all(row["effective_state"] == "ended" for row in reader.listing("users", scope="project")["items"])
    assert all(row["freshness"] == "ended" for row in reader.listing(scope="project", include_ended=True)["items"])
    controller_lifecycle(admin, receiver, project, reader)
    print(json.dumps({"controller_lifecycle_http": True, "parent_worker_http": True, "identity_switch_no_write": True,
                      "core_observer_http": True, "two_scoped_actors": True, "waiting_not_idle_before_threshold": True,
                      "approval_not_idle": True, "ended_not_human_offline": True, "real_cli_account": False}))


if __name__ == "__main__":
    main()
