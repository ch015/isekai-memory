"""Real HTTP: publisher observes a different user's claim, renewal and receipt."""

import json
import os
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

from e2e_smoke import ADMIN_TOKEN, CROSS_TOKEN, PROJECT_ID, READ_TOKEN, mcp_tool, request
from helpers import handoff_arguments

from isekai_memory.registry.verification import canonical_bytes, digest_bytes


def main():
    collaborator = os.environ["MEMORY_COLLABORATOR_TOKEN"]
    source = handoff_arguments()
    source["project_id"] = PROJECT_ID
    source["phase_attempt_id"] = "collaboration-" + uuid4().hex
    for field in ("task_envelope", "result_envelope"):
        source[field]["phase_attempt_id"] = source["phase_attempt_id"]
    source["envelope_digest"] = digest_bytes(canonical_bytes(source["task_envelope"]) + canonical_bytes(source["result_envelope"]))
    hid = mcp_tool(ADMIN_TOKEN, "memory_handoff_push", source)["handoff_id"]
    available = mcp_tool(collaborator, "memory_handoff_inbox", {"project_id": PROJECT_ID})
    assert hid in {item["handoff_id"] for item in available["items"]}
    args = {"project_id": PROJECT_ID, "handoff_id": hid, "claim_token": secrets.token_urlsafe(32)}
    claimed = mcp_tool(collaborator, "memory_handoff_claim", args)
    assert claimed["claimed_by"] == "collaborator" and claimed["from_user"] == "e2e-user"
    args["claim_generation"] = claimed["claim_generation"]
    target = (datetime.fromisoformat(claimed["lease_expires_at"]) + timedelta(seconds=30)).isoformat()
    renewal = {**args, "lease_expires_at": target}
    for token in (ADMIN_TOKEN, READ_TOKEN, CROSS_TOKEN):
        status, _, _ = request("/tools/memory_handoff_renew", token=token, payload=renewal)
        assert status in (403, 409)
    assert mcp_tool(collaborator, "memory_handoff_renew", renewal)["extended"]
    assert not mcp_tool(collaborator, "memory_handoff_renew", renewal)["extended"]
    mcp_tool(collaborator, "memory_handoff_ack", args)
    observed = mcp_tool(READ_TOKEN, "memory_handoff_status", {"project_id": PROJECT_ID, "handoff_id": hid})
    assert observed["handoff"]["delivery_state"] == "acknowledged"
    assert observed["handoff"]["claimed_by"] == "collaborator"
    assert "claim_token_digest" not in observed["handoff"]
    print(json.dumps({"multiuser_handoff": True, "absolute_renewal": True, "publisher_receipt": True}))


if __name__ == "__main__":
    main()
