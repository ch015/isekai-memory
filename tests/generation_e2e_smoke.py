"""Real HTTP enqueue/review/read plus a separate offline worker CLI process."""

import json
import os
import subprocess
import sys
from uuid import uuid4

from e2e_smoke import ADMIN_TOKEN, PROJECT_ID, READ_TOKEN, mcp
from helpers import handoff_arguments

from isekai_memory.registry.verification import canonical_bytes, digest_bytes


def call(name, arguments, *, token=ADMIN_TOKEN):
    result = mcp("tools/call", token=token, params={"name": name, "arguments": {"project_id": PROJECT_ID, **arguments}})
    assert not result["isError"], result
    return result["structuredContent"]


def work():
    result = subprocess.run(
        [sys.executable, "-m", "isekai_memory.main", "--run-generation", "--project-id", PROJECT_ID, "--max-jobs", "20"],
        env={**os.environ, "ISEKAI_MEMORY_GENERATION_ENABLED": "true"},
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout)


def main():
    args = handoff_arguments()
    attempt = uuid4().hex
    args.update(project_id=PROJECT_ID, phase_attempt_id=attempt, phase_id="generation-e2e")
    args["task_envelope"]["phase_attempt_id"] = attempt
    args["result_envelope"]["phase_attempt_id"] = attempt
    args["result_envelope"]["summary"] = "M4 durable extraction acceptance result"
    args["envelope_digest"] = digest_bytes(canonical_bytes(args["task_envelope"]) + canonical_bytes(args["result_envelope"]))
    sid = call("memory_handoff_push", args)["handoff_id"]
    call("memory_generation_enqueue", {"kind": "extract"})
    processed = work()
    assert processed["cost_microusd"] == 0
    jobs = call("memory_generation_list", {"status": "succeeded"})["items"]
    job = next(row for row in jobs if row["source_key"] == sid)
    assert job["outcome"]["code"] == "proposed"
    mid = job["outcome"]["memory_id"]
    assert call("memory_search", {"query": "M4 durable extraction"}, token=READ_TOKEN)["items"] == []
    call("memory_experience_review", {"memory_id": mid, "action": "approve", "expected_version": 1})
    call("memory_generation_enqueue", {"kind": "summary", "phase_id": "generation-e2e"})
    assert call("memory_summary_read", {"phase_id": "generation-e2e"}, token=READ_TOKEN)["status"] == "missing"
    work()
    ready = call("memory_summary_read", {"phase_id": "generation-e2e"}, token=READ_TOKEN)
    assert ready["status"] == "ready" and ready["items"][0]["memory_id"] == mid
    call("memory_experience_review", {"memory_id": mid, "action": "forget", "expected_version": 2})
    stale = call("memory_summary_read", {"phase_id": "generation-e2e"}, token=READ_TOKEN)
    assert stale["status"] == "stale" and stale["items"] == []
    assert work()["processed"] == 0
    print(json.dumps({"generation_http_and_worker_cli": True, "pending_then_reviewed": True, "forget_invalidates_summary": True}))


if __name__ == "__main__":
    main()
