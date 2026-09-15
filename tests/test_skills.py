"""Native Skill contracts, safe resources and deterministic archive semantics."""

import base64
import copy
import io
import json
import tarfile
from uuid import uuid4

import pytest

from isekai_memory.registry.verification import canonical_bytes, digest_bytes
from isekai_memory.server.auth import Principal, authorize_tool
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.validation import validate_tool_arguments
from isekai_memory.skills.export import build
from isekai_memory.skills.submissions import prepare


def body(memory_id):
    return {
        "title": "검증된 재시도 절차", "description": "Use after a lost response to check durable receipts.",
        "triggers": ["A response was lost and the original request identity is available."],
        "steps": [{"instruction": "Check the original receipt before requesting a retry.", "sources": [memory_id]}],
        "validation": ["The receipt identity matches the original request and no duplicate work was created."],
        "resources": [{"name": "checklist", "content": "Record the request ID and observed receipt ID."}],
    }


def arguments():
    mid = str(uuid4())
    return {"project_id": "p", "name": "receipt-retry", "idempotency_key": "proposal", "body": body(mid),
            "sources": [{"memory_id": mid, "version": 2}]}


def export_fixture():
    args = arguments()
    return {**args, "skill_id": str(uuid4()), "revision_id": str(uuid4()), "revision": 2, "version": 2,
            "classification": "internal", "source_lock_digest": "sha256:" + "1" * 64,
            "source_watermark": "sha256:" + "2" * 64, "content_digest": "sha256:" + "3" * 64,
            "approved_at": "2026-09-10T00:00:00+00:00"}


def test_deterministic_unsigned_native_export_has_three_independent_digests():
    skill = export_fixture()
    first = build(skill)
    assert first == build(skill) and not first["signed"] and first["usage"] == "export_only"
    data = base64.b64decode(first["archive_base64"])
    assert digest_bytes(data) == first["archive_digest"]
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        assert all(member.isfile() and member.mode == 0o644 and member.mtime == 0 for member in archive)
        manifest_bytes = archive.extractfile("manifest.json").read()
        manifest = json.loads(manifest_bytes)
        assert manifest["kind"] == "skill" and manifest["execution_mode"] == "instruction"
        assert manifest["requested_actions"] == [] and manifest["required_capabilities"] == []
        assert manifest["version"] == "2.0.0"
        assert digest_bytes(manifest_bytes) == first["manifest_digest"]
        assert digest_bytes(canonical_bytes({k: v for k, v in manifest.items() if k != "artifact_digest"})) == first["artifact_digest"]
        for record in manifest["files"]:
            content = archive.extractfile(record["path"]).read()
            assert len(content) == record["size"] and digest_bytes(content) == record["digest"]


@pytest.mark.parametrize("name", ["../escape", "/tmp/file", "a/b", "a\\b", "script.py", "-bad", "a\x00b"])
def test_resource_paths_cannot_escape_or_request_executables(name):
    args = arguments()
    args["body"]["resources"][0]["name"] = name
    with pytest.raises(MemoryToolError):
        validate_tool_arguments("memory_skill_propose", args)
    data = export_fixture()
    data["body"] = args["body"]
    with pytest.raises(MemoryToolError):
        build(data)


def test_duplicate_sources_and_foreign_step_bindings_rejected():
    args = arguments()
    args["sources"].append({**args["sources"][0], "version": 3})
    with pytest.raises(MemoryToolError):
        prepare(args)
    args = arguments()
    args["body"]["steps"][0]["sources"] = [str(uuid4())]
    with pytest.raises(MemoryToolError):
        prepare(args)


def test_resource_duplicate_and_total_body_budget_rejected():
    args = arguments()
    args["body"]["resources"] *= 2
    with pytest.raises(MemoryToolError):
        prepare(args)
    args = arguments()
    args["body"]["steps"] = [{"instruction": "a" * 1024, "sources": args["body"]["steps"][0]["sources"]}] * 12
    args["body"]["resources"] = [{"name": "file-" + str(i), "content": "b" * 4096} for i in range(4)]
    with pytest.raises(MemoryToolError):
        prepare(args)


def test_normalized_body_replay_is_stable():
    args = arguments()
    other = copy.deepcopy(args)
    other["body"]["title"] = "  " + args["body"]["title"] + "  "
    assert prepare(args) == prepare(other)


@pytest.mark.parametrize("name", ["memory_skill_generate", "memory_skill_revise", "memory_skill_review",
                                  "memory_skill_list", "memory_skill_inspect", "memory_skill_export"])
def test_review_and_export_require_admin_scope(name):
    with pytest.raises(MemoryToolError):
        authorize_tool(Principal("u", "p", frozenset({"read", "write"})), name, {"project_id": "p"})
    with pytest.raises(MemoryToolError):
        authorize_tool(Principal("u", "p", frozenset({"admin"})), name, {"project_id": "other"})


def test_export_requires_exact_lock_and_lifecycle_version():
    with pytest.raises(MemoryToolError):
        validate_tool_arguments("memory_skill_export", {"project_id": "p", "revision_id": str(uuid4())})
