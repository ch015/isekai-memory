"""Strict continuity tool boundaries, routing policy and portable snapshot validation."""

import base64
import hashlib
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from isekai_memory.continuity import policies, snapshots
from isekai_memory.continuity.common import canonical, digest
from isekai_memory.continuity.delivery import validate_units
from isekai_memory.continuity.tools import CONTINUITY_SCOPES, CONTINUITY_TOOLS
from isekai_memory.server.auth import Principal, authorize_tool
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.validation import validate_tool_arguments
from tests.helpers import continuation_package


def policy_body(**overrides):
    return {"enabled": True, "default_recipient_user_ids": ["admin", "admin2"], "default_backup_user_ids": [],
            "sender_rules": [], "retention_hours": 168, "lease_seconds": 300,
            "checkpoint_interval_seconds": 60, "checkpoint_max_bytes": 1048576,
            "checkpoint_allowed_paths": ["src", "tests", "README.md"], "allow_emergency_takeover": False, **overrides}


def captured():
    raw = b"print('portable checkpoint')\n"
    snapshot = {"schema_version": 1, "files": [{"path": "src/main.py", "content_base64": base64.b64encode(raw).decode(),
                                               "digest": "sha256:" + hashlib.sha256(raw).hexdigest()}]}
    package = continuation_package()
    artifact = package["artifacts"][0]
    artifact.update(source_id="memory-checkpoint", reference="snapshot-" + digest(snapshot)[7:],
                    digest=digest(snapshot), size_bytes=len(canonical(snapshot)))
    return package, snapshot


@pytest.mark.parametrize("tool", CONTINUITY_TOOLS, ids=lambda tool: tool["name"])
def test_catalog_strict_and_project_authorized(tool):
    schema = tool["inputSchema"]
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert "project_id" in schema["required"]
    with pytest.raises(MemoryToolError):
        authorize_tool(Principal("admin", "project-a", frozenset({"admin"})), tool["name"], {"project_id": "project-b"})
    if CONTINUITY_SCOPES[tool["name"]] == "admin":
        with pytest.raises(MemoryToolError):
            authorize_tool(Principal("writer", "project-a", frozenset({"read", "write"})), tool["name"], {"project_id": "project-a"})


def test_sender_override_replaces_defaults_and_multiple_active_recipients():
    body = policy_body(sender_rules=[{"from_user_id": "writer", "recipient_user_ids": ["b", "c", "d"], "backup_user_ids": ["e"]}])
    assert policies.validate(body) == {"admin", "admin2", "b", "c", "d", "e"}
    assert policies.resolve(body, "writer") == (["b", "c", "d"], ["e"])
    assert policies.resolve(body, "someone-else") == (["admin", "admin2"], [])


@pytest.mark.parametrize("mutation", [
    {"default_backup_user_ids": ["admin"]},
    {"sender_rules": [{"from_user_id": "writer", "recipient_user_ids": ["writer"], "backup_user_ids": []}]},
    {"sender_rules": [{"from_user_id": "writer", "recipient_user_ids": ["admin"], "backup_user_ids": ["admin"]}]},
    {"sender_rules": [{"from_user_id": "writer", "recipient_user_ids": ["admin"], "backup_user_ids": []}] * 2},
    {"checkpoint_allowed_paths": ["../"]},
])
def test_invalid_policy_relations(mutation):
    with pytest.raises(MemoryToolError):
        policies.validate(policy_body(**mutation))


@pytest.mark.parametrize("path", ["/root", "../file", "src/../file", "src//a", "src/./a", "src\\a", "C:/a", "src/.env",
                                 ".git/config", "src/credentials.json", "src/key.pem", "src/a\n", "src/.codex/config"])
def test_unsafe_paths(path):
    with pytest.raises(MemoryToolError):
        snapshots.safe_path(path)


def test_snapshot_round_trip_binds_bytes_and_budget():
    package, snapshot = captured()
    assert snapshots.validate(snapshot, package, policy_body()) == digest(snapshot)
    with pytest.raises(MemoryToolError):
        snapshots.validate(snapshot, package, policy_body(checkpoint_max_bytes=1))
    with pytest.raises(MemoryToolError):
        snapshots.validate(snapshot, package, policy_body(checkpoint_allowed_paths=[]))


@pytest.mark.parametrize("mutation", ["digest", "base64", "duplicate", "case_collision", "path_collision", "locator", "size", "secret", "no_bytes", "not_captured"])
def test_snapshot_corruption(mutation):
    package, snapshot = captured()
    file = snapshot["files"][0]
    if mutation == "digest":
        file["digest"] = "sha256:" + "0" * 64
    elif mutation == "base64":
        file["content_base64"] += "\n"
    elif mutation in {"duplicate", "case_collision", "path_collision"}:
        extra = deepcopy(file)
        extra["path"] = {"duplicate": file["path"], "case_collision": "SRC/main.py", "path_collision": "src/main.py/file"}[mutation]
        snapshot["files"].append(extra)
    elif mutation == "locator":
        package["artifacts"][0]["source_id"] = "personal-files"
    elif mutation == "size":
        package["artifacts"][0]["size_bytes"] += 1
    elif mutation == "secret":
        raw = b"-----BEGIN RSA PRIVATE KEY-----"
        file.update(content_base64=base64.b64encode(raw).decode(), digest="sha256:" + hashlib.sha256(raw).hexdigest())
    elif mutation == "no_bytes":
        snapshot = None
    else:
        package["workspace"] = {"state": "clean"}
    with pytest.raises(MemoryToolError):
        snapshots.validate(snapshot, package, policy_body())


def test_unit_scope_and_self_identity_not_caller_controlled():
    with pytest.raises(MemoryToolError):
        validate_units([{"key": "one", "assignee_user_ids": ["outsider"]}], ["admin"])
    with pytest.raises(MemoryToolError):
        validate_units([{"key": "one", "assignee_user_ids": ["admin"]}] * 2, ["admin"])
    package, snapshot = captured()
    with pytest.raises(MemoryToolError):
        validate_tool_arguments("memory_checkpoint_save", {"project_id": "p", "work_id": "one", "expected_version": 0,
            "from_user": "departed-user", "continuation": package, "snapshot": snapshot, "classification": "internal",
            "lock_snapshot_digest": "sha256:" + "a" * 64, "idempotency_key": "one"})
