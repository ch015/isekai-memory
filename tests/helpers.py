from __future__ import annotations

import gzip
import hashlib
import io
import tarfile
from typing import Any

from isekai_memory.registry.verification import canonical_bytes, digest_bytes


def build_artifact_archive(*, version: str = "1.0.0", archive_payload: bytes | None = None) -> tuple[bytes, dict[str, Any]]:
    payload = b'{"id":"demo","version":"1.0.0"}'
    record = {
        "path": "foundation.json",
        "digest": digest_bytes(payload),
        "size": len(payload),
        "mode": "data",
        "executable": False,
    }
    manifest: dict[str, Any] = {
        "schema_version": 2,
        "kind": "foundation",
        "id": "demo",
        "version": version,
        "protocol_major": 1,
        "requires": {"core_protocol": ">=1 <2"},
        "files": [record],
        "content": {"path": "foundation.json", "schema": "urn:isekai:schema:foundation-policy"},
        "provenance": {
            "source_repository": "local://test",
            "resolved_commit": "abcdef0",
            "source_tree_digest": "sha256:" + "1" * 64,
            "builder_id": "test-builder",
            "builder_version": "1.0.0",
            "built_at": "2026-08-25T00:00:00Z",
        },
        "created_at": "2026-08-25T00:00:00Z",
    }
    manifest["artifact_digest"] = digest_bytes(canonical_bytes(manifest))
    manifest_bytes = canonical_bytes(manifest)
    output = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive,
    ):
        for name, content in (("manifest.json", manifest_bytes), ("foundation.json", archive_payload or payload)):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o644
            member.mtime = 0
            archive.addfile(member, io.BytesIO(content))
    return output.getvalue(), manifest


def handoff_arguments() -> dict[str, Any]:
    lock_digest = "sha256:" + "2" * 64
    context_digest = "sha256:" + "3" * 64
    raw_output = "completed"
    raw_digest = "sha256:" + hashlib.sha256(raw_output.encode()).hexdigest()
    common = {
        "correlation_id": "correlation-1",
        "work_bundle_id": "work-1",
        "unit_id": "unit-1",
        "phase_attempt_id": "attempt-1",
        "session_id": "session-1",
    }
    task = {
        **common,
        "operation_id": "operation-task",
        "type": "task_envelope",
        "task_id": "task-1",
        "role": "developer",
        "objective": "Implement the unit",
        "acceptance_criteria": ["tests pass"],
        "allowed_actions": ["source.read"],
        "forbidden_actions": [],
        "required_outputs": ["result"],
        "workspace_root": ".",
        "lock_snapshot_digest": lock_digest,
        "context_bundle_ref": "context-1",
        "context_bundle_digest": context_digest,
        "result_path": "result.json",
        "deadline": "2026-08-26T00:00:00Z",
    }
    result = {
        **common,
        "operation_id": "operation-result",
        "type": "result_envelope",
        "task_id": "task-1",
        "status": "succeeded",
        "summary": "Completed",
        "outputs": ["result.json"],
        "evidence_refs": ["evidence-1"],
        "unresolved": [],
        "context_usage": {"mode": "exact", "used": 10, "capacity": 100},
        "raw_output_ref": "raw.txt",
        "raw_output_digest": raw_digest,
        "started_at": "2026-08-25T00:00:00Z",
        "ended_at": "2026-08-25T00:01:00Z",
    }
    envelope_digest = "sha256:" + hashlib.sha256(canonical_bytes(task) + canonical_bytes(result)).hexdigest()
    return {
        "project_id": "project-1",
        "unit_id": "unit-1",
        "phase_attempt_id": "attempt-1",
        "phase_id": "implement",
        "result_status": "succeeded",
        "classification": "internal",
        "task_envelope": task,
        "result_envelope": result,
        "context_digest": context_digest,
        "raw_output": raw_output,
        "lock_snapshot_digest": lock_digest,
        "envelope_digest": envelope_digest,
    }


def continuation_package() -> dict[str, Any]:
    """Synthetic descriptors only: no real repository or artifact is fetched."""
    return {
        "schema_version": 1, "goal": "Finish the shared change", "verified_state": "Unit tests passed before handoff",
        "repository": {"source_id": "repo-main", "commit": "a" * 40, "branch": "feature-handoff"},
        "workspace": {"state": "captured", "snapshot_artifact_id": "workspace-1"},
        "artifacts": [{"id": "workspace-1", "source_id": "team-artifacts", "reference": "snapshot-1",
                       "kind": "workspace_snapshot", "digest": "sha256:" + "b" * 64, "size_bytes": 1024}],
        "remaining_work": ["Integration verification"], "next_steps": ["Verify and restore the workspace snapshot"],
        "blockers": [], "decisions": ["Preserve the existing API contract"],
    }
