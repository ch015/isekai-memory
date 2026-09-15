"""Real HTTP: explicitly capable recipient receives portable descriptors only."""

import json
import os
import secrets
from uuid import uuid4

from e2e_smoke import ADMIN_TOKEN, PROJECT_ID, mcp_tool, request
from helpers import continuation_package, handoff_arguments

from isekai_memory.handoff.service import _compute_envelope_digest, _digest


def main():
    recipient = os.environ["MEMORY_COLLABORATOR_TOKEN"]
    source = handoff_arguments()
    source.update(project_id=PROJECT_ID, phase_attempt_id="m8-e2e-" + uuid4().hex,
                  recipient_user_id="collaborator", continuation=continuation_package())
    for field in ("task_envelope", "result_envelope"):
        source[field]["phase_attempt_id"] = source["phase_attempt_id"]
    source["envelope_digest"] = _compute_envelope_digest(source["task_envelope"], source["result_envelope"])
    published = mcp_tool(ADMIN_TOKEN, "memory_handoff_push", source)
    hid = published["handoff_id"]
    assert published["handoff_version"] == 2
    assert hid not in {row["id"] for row in mcp_tool(recipient, "memory_handoff_list", {"project_id": PROJECT_ID})}
    assert hid not in {row["handoff_id"] for row in mcp_tool(ADMIN_TOKEN, "memory_handoff_inbox", {"project_id": PROJECT_ID})["items"]}
    assert hid in {row["handoff_id"] for row in mcp_tool(recipient, "memory_handoff_inbox", {"project_id": PROJECT_ID})["items"]}
    args = {"project_id": PROJECT_ID, "handoff_id": hid, "claim_token": secrets.token_urlsafe(32)}
    status, _, _ = request("/tools/memory_handoff_claim", token=recipient, payload=args)
    assert status >= 400  # Recipient alone is insufficient: explicit contract opt-in is required.
    status, _, _ = request("/tools/memory_handoff_claim", token=ADMIN_TOKEN, payload={**args, "accept_handoff_version": 2})
    assert status >= 400  # Administrator role does not override the recipient.
    received = mcp_tool(recipient, "memory_handoff_claim", {**args, "accept_handoff_version": 2})
    assert received["continuation"] == source["continuation"]
    assert received["continuation_digest"] == _digest(source["continuation"])
    assert received["preflight"]["status"] == "verification_required" and not received["preflight"]["automatic_resume"]
    recovered = mcp_tool(recipient, "memory_handoff_get_claimed", args)
    assert recovered["payload_digest"] == received["payload_digest"]
    mcp_tool(recipient, "memory_handoff_ack", {**args, "claim_generation": received["claim_generation"]})
    print(json.dumps({"recipient_enforced": True, "legacy_consumer_guarded": True,
                      "portable_descriptor_roundtrip": True, "core_preflight_still_required": True}))


if __name__ == "__main__":
    main()
