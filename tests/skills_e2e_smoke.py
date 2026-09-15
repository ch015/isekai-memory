"""Real Skill HTTP + worker CLI + optional unchanged Core artifact verifier."""

import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

from e2e_smoke import READ_TOKEN
from generation_e2e_smoke import call, work
from helpers import handoff_arguments

from isekai_memory.registry.verification import canonical_bytes, digest_bytes


def main():
    args = handoff_arguments()
    args["phase_attempt_id"] = uuid4().hex
    args.pop("project_id")
    args["task_envelope"]["phase_attempt_id"] = args["phase_attempt_id"]
    args["result_envelope"]["phase_attempt_id"] = args["phase_attempt_id"]
    args["envelope_digest"] = digest_bytes(canonical_bytes(args["task_envelope"]) + canonical_bytes(args["result_envelope"]))
    sid = call("memory_handoff_push", args)["handoff_id"]
    mid = call("memory_experience_propose", {"source_handoff_id": sid, "idempotency_key": uuid4().hex,
               "kind": "procedure", "title": "Receipt verification", "content": "Check the original receipt before retrying."})["memory_id"]
    call("memory_experience_review", {"memory_id": mid, "expected_version": 1, "action": "approve"})
    refs = [{"memory_id": mid, "version": 2}]
    queued = call("memory_skill_generate", {"sources": refs})
    outcomes = work()["results"]
    scaffold = next(row for row in outcomes if row["job_id"] == queued["job"]["job_id"])
    assert scaffold["code"] == "skill_proposed"
    body = {
        "title": "Receipt validation", "description": "Validate a durable receipt after a lost response.",
        "triggers": ["A response is lost and the original request identity is known."],
        "steps": [{"instruction": "Compare the receipt and original request identities.", "sources": [mid]}],
        "validation": ["Request IDs match; no duplicate execution occurred."],
        "resources": [{"name": "checklist", "content": "Capture both identifiers for human review."}],
    }
    revision = call("memory_skill_revise", {"skill_id": scaffold["skill_id"], "expected_revision": 1,
                    "idempotency_key": uuid4().hex, "sources": refs, "body": body})
    call("memory_skill_review", {"revision_id": revision["revision_id"], "expected_version": 1, "action": "approve"})
    assert call("memory_skill_read", {"revision_id": revision["revision_id"]}, token=READ_TOKEN)["skill"]["body"] == body
    export_args = {"revision_id": revision["revision_id"], "expected_version": 2, "source_lock_digest": args["lock_snapshot_digest"]}
    exported = call("memory_skill_export", export_args)
    assert exported == call("memory_skill_export", export_args)
    imported = call("memory_skill_import", {
        **{key: exported[key] for key in ("archive_base64", "archive_digest", "manifest_digest", "artifact_digest")},
        "classification": "internal", "idempotency_key": uuid4().hex,
    })
    assert imported["status"] == "quarantined" and not imported["trusted"]
    assert call("memory_skill_import_inspect", {"import_id": imported["import_id"]})["payload"]["body"] == body
    call("memory_skill_import_forget", {"import_id": imported["import_id"], "expected_version": 1})
    assert call("memory_skill_import_inspect", {"import_id": imported["import_id"]})["payload"] == {}
    if os.environ.get("MEMORY_CORE_PYTHON") and os.environ.get("MEMORY_CORE_SOURCE"):
        subprocess.run([os.environ["MEMORY_CORE_PYTHON"], str(Path(__file__).with_name("core_skill_verifier_smoke.py"))],
                       input=json.dumps(exported), text=True, check=True, timeout=30)
    call("memory_experience_review", {"memory_id": mid, "expected_version": 2, "action": "forget"})
    inspected = call("memory_skill_inspect", {"revision_id": revision["revision_id"]})["skill"]
    assert inspected["status"] == "forgotten" and inspected["body"] == {}
    print(json.dumps({"skill_http_and_worker_cli": True, "reviewed_deterministic_export": True,
                      "quarantined_import_and_erasure": True, "source_forget_erases_skill": True}))


if __name__ == "__main__":
    main()
