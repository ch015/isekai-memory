"""Bounded portable descriptors; no network, files, credentials or execution."""

import hashlib
import json

from isekai_memory.server.errors import MemoryToolError

OPAQUE = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]*$",
          "not": {"pattern": r"\s"}}
TEXT = {"type": "string", "minLength": 1, "maxLength": 2048, "pattern": r"\S"}
TEXT_LIST = {"type": "array", "items": TEXT, "maxItems": 20, "uniqueItems": True}
RECIPIENT = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": r"^[^\s\x00-\x1f\x7f]+$",
             "not": {"pattern": r"\s"}}
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "goal", "verified_state", "repository", "workspace", "artifacts",
                 "remaining_work", "next_steps", "blockers"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1, 2]},
        "compatibility_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "goal": TEXT, "verified_state": TEXT, "remaining_work": TEXT_LIST,
        "next_steps": {**TEXT_LIST, "minItems": 1}, "blockers": TEXT_LIST, "decisions": TEXT_LIST,
        "repository": {
            "type": "object", "additionalProperties": False, "required": ["source_id", "commit"],
            "properties": {
                "source_id": OPAQUE,
                "commit": {"type": "string", "pattern": "^(?:[0-9a-f]{40}|[0-9a-f]{64})$", "not": {"pattern": r"\s"}},
                "branch": {"type": "string", "minLength": 1, "maxLength": 128, "pattern": r"^[^\x00-\x1f\x7f]+$"},
            },
        },
        "workspace": {
            "oneOf": [
                {"type": "object", "additionalProperties": False, "required": ["state"],
                 "properties": {"state": {"const": "clean"}}},
                {"type": "object", "additionalProperties": False, "required": ["state", "snapshot_artifact_id"],
                 "properties": {"state": {"const": "captured"}, "snapshot_artifact_id": OPAQUE}},
                {"type": "object", "additionalProperties": False, "required": ["state", "reason"],
                 "properties": {"state": {"const": "unavailable"}, "reason": TEXT}},
            ],
        },
        "artifacts": {
            "type": "array", "maxItems": 20,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "source_id", "reference", "kind", "digest", "size_bytes"],
                "properties": {
                    "id": OPAQUE, "source_id": OPAQUE, "reference": OPAQUE,
                    "kind": {"enum": ["workspace_snapshot", "output", "evidence"]},
                    "digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$", "not": {"pattern": r"\s"}},
                    "size_bytes": {"type": "integer", "minimum": 1, "maximum": 104857600},
                },
            },
        },
    },
}

# v1 keeps its exact Git contract; v2 is an allowlisted directory snapshot with no invented commit.
GIT_SOURCE = SCHEMA["properties"]["repository"]
DIRECTORY_SOURCE = {"type": "object", "additionalProperties": False, "required": ["source_id", "kind"],
                    "properties": {"source_id": OPAQUE, "kind": {"const": "directory"}}}
SCHEMA["properties"]["repository"] = {"oneOf": [GIT_SOURCE, DIRECTORY_SOURCE]}
SCHEMA["allOf"] = [{"if": {"properties": {"schema_version": {"const": 1}}},
                    "then": {"properties": {"repository": GIT_SOURCE}},
                    "else": {"properties": {"repository": DIRECTORY_SOURCE,
                                               "workspace": {"properties": {"state": {"enum": ["captured", "unavailable"]}}}}}}]


def invalid(message):
    return MemoryToolError(message, data={"error_code": "MEM-HANDOFF-0012"}, http_status=400)


def validate(package):
    # Also validate direct service calls, not only the MCP boundary.
    from jsonschema import Draft202012Validator

    if not Draft202012Validator(SCHEMA).is_valid(package):
        raise invalid("Invalid continuation schema")
    encoded = json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > 65536:
        raise invalid("Continuation exceeds the 64 KiB canonical payload limit")
    artifacts = {item["id"]: item for item in package["artifacts"]}
    if len(artifacts) != len(package["artifacts"]):
        raise invalid("Continuation artifact IDs must be unique")
    workspace = package["workspace"]
    if workspace["state"] == "captured":
        snapshot = artifacts.get(workspace["snapshot_artifact_id"])
        if snapshot is None or snapshot["kind"] != "workspace_snapshot":
            raise invalid("Captured workspace must reference a declared workspace snapshot")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def delivery_fields(row):
    if row.get("handoff_version", 1) == 1:
        return {}
    package = row["continuation"]
    reasons = []
    if package is None:
        reasons.append("continuation_missing")
    else:
        if package["workspace"]["state"] == "unavailable":
            reasons.append("workspace_unavailable")
        if package["blockers"]:
            reasons.append("sender_blockers")
    return {
        "handoff_version": 2, "recipient_user_id": row["recipient_user_id"],
        "continuation": package, "continuation_digest": row["continuation_digest"],
        "payload_digest": row["payload_digest"],
        "preflight": {
            "status": "blocked" if reasons else "verification_required", "blocked_reasons": reasons,
            "required_checks": ["claim_identity_and_lease", "payload_integrity", "source_lock_policy",
                                "repository_commit", "artifact_access_size_digest", "isolated_workspace",
                                "local_checks_and_approval", "lease_recheck"],
            "automatic_resume": False,
        },
    }
