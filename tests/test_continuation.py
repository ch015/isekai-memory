"""M8 package boundaries and deterministic binding without external I/O."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from isekai_memory.handoff import continuation
from isekai_memory.handoff.service import _digest, push_handoff
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.validation import validate_tool_arguments
from tests.helpers import continuation_package, handoff_arguments


def test_valid_package_is_deterministic_and_tool_schema_accepts_it():
    package = continuation_package()
    validate_tool_arguments("memory_handoff_push", {**handoff_arguments(), "recipient_user_id": "bob", "continuation": package})
    assert continuation.validate(package) == _digest(package)
    assert continuation.validate(dict(reversed(list(package.items())))) == _digest(package)


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("goal", " \n"), ("next_steps", []),
    ("next_steps", ["x"] * 21), ("remaining_work", ["x", "x"]), ("verified_state", "x" * 2049),
    ("repository", {"source_id": "repo-main", "commit": "main"}),
    ("repository", {"source_id": "https://user:secret@example.test/repo", "commit": "a" * 40}),
    ("repository", {"source_id": "repo-main", "commit": "a" * 40 + "\n"}),
    ("repository", {"source_id": "repo-main\n", "commit": "a" * 40}),
    ("workspace", {"state": "captured"}), ("workspace", {"state": "dirty"}),
    ("workspace", {"state": "unavailable", "reason": " "}),
    ("workspace", {"state": "clean", "snapshot_artifact_id": "workspace-1"}),
    ("workspace", {"state": "clean", "path": "/Users/alice/project"}),
])
def test_package_rejects_nonportable_or_incomplete_inputs(field, value):
    package = {**continuation_package(), field: value}
    with pytest.raises(MemoryToolError):
        continuation.validate(package)


@pytest.mark.parametrize("field,value", [
    ("reference", "../snapshot"), ("reference", "file:///tmp/snapshot"), ("reference", "https://host/snapshot?token=secret"),
    ("source_id", "source\n"), ("digest", "sha256:" + "c" * 64 + "\n"),
    ("digest", "not-a-digest"), ("size_bytes", True), ("size_bytes", 0), ("size_bytes", 104857601),
    ("kind", "script"), ("command", "execute something"),
])
def test_artifact_descriptors_cannot_be_commands_paths_or_unbounded_data(field, value):
    package = continuation_package()
    package["artifacts"][0][field] = value
    with pytest.raises(MemoryToolError):
        continuation.validate(package)


@pytest.mark.parametrize("recipient", [None, "", "a b", "bob\n", "x" * 129, True])
def test_invalid_recipient_schema(recipient):
    with pytest.raises(MemoryToolError):
        validate_tool_arguments("memory_handoff_push", {**handoff_arguments(), "recipient_user_id": recipient})


def test_unique_artifacts_and_snapshot_reference_are_enforced():
    package = continuation_package()
    for artifacts in ([], [package["artifacts"][0]] * 2, [{**package["artifacts"][0], "kind": "output"}]):
        with pytest.raises(MemoryToolError):
            continuation.validate({**package, "artifacts": artifacts})


def test_total_utf8_budget_is_enforced_beyond_individual_field_limits():
    package = continuation_package()
    package["next_steps"] = ["가" * 2040 + str(i) for i in range(20)]
    with pytest.raises(MemoryToolError, match="64 KiB"):
        continuation.validate(package)


@pytest.mark.parametrize("workspace", [{"state": "clean"}, {"state": "unavailable", "reason": "Snapshot not uploaded"}])
def test_clean_or_explicitly_unavailable_workspace_is_representable(workspace):
    package = {**continuation_package(), "workspace": workspace, "artifacts": []}
    assert continuation.validate(package).startswith("sha256:")


def test_preflight_never_grants_execution_or_treats_sender_claim_as_verified():
    package = continuation_package()
    row = {"handoff_version": 2, "recipient_user_id": "bob", "continuation": package,
           "continuation_digest": _digest(package), "payload_digest": "sha256:" + "d" * 64}
    result = continuation.delivery_fields(row)
    assert result["preflight"]["status"] == "verification_required"
    assert not result["preflight"]["automatic_resume"]
    assert "ready_to_resume" not in result["preflight"]
    for packet, reason in ((None, "continuation_missing"),
                           ({**package, "blockers": ["Need review"]}, "sender_blockers"),
                           ({**package, "workspace": {"state": "unavailable", "reason": "Local only"}}, "workspace_unavailable")):
        preflight = continuation.delivery_fields({**row, "continuation": packet})["preflight"]
        assert preflight["status"] == "blocked" and reason in preflight["blocked_reasons"]
    assert continuation.delivery_fields({}) == {}


@pytest.mark.asyncio
async def test_extension_changes_payload_digest_without_changing_legacy_envelope(monkeypatch):
    captured = []

    async def insert(**kwargs):
        captured.append(kwargs)
        return {"id": uuid4(), "created_at": datetime.now(UTC), "expires_at": kwargs["expires_at"]}

    monkeypatch.setattr("isekai_memory.handoff.service.queries.insert_handoff", insert)
    args = handoff_arguments()
    await push_handoff(args, from_user="alice")
    legacy = {**args, "from_user": "alice", "task_summary": None, "handoff_note": None,
              "passed_checks": [], "artifacts_produced": []}
    assert captured[0]["payload_digest"] == _digest(legacy)
    for recipient in ("bob", "carol"):
        await push_handoff({**args, "recipient_user_id": recipient, "continuation": continuation_package()}, from_user="alice")
    changed = deepcopy(continuation_package())
    changed["next_steps"] = ["Different next step"]
    await push_handoff({**args, "recipient_user_id": "bob", "continuation": changed}, from_user="alice")
    assert len({item["payload_digest"] for item in captured}) == 4
    assert {item["envelope_digest"] for item in captured} == {args["envelope_digest"]}
