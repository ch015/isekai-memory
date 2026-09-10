"""Real two-project HTTP sharing, feedback and pushed source deletion; no connectors."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from e2e_smoke import ADMIN_TOKEN, CROSS_TOKEN, PROJECT_ID, mcp, request
from generation_e2e_smoke import call

from isekai_memory.retrieval.citations import canonical, digest


def main():
    until = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    body = {"title": "M6 Wiki reference", "content": "Check the durable receipt before retrying."}
    doc = call("memory_knowledge_sync", {"provider": "pushed_wiki_v1", "source_key": uuid4().hex, "source_revision": "revision-1",
               "expected_version": 0, "classification": "internal", "valid_until": until, **body, "content_digest": digest(canonical(body))})
    asset = {"asset_kind": "knowledge", "asset_id": doc["document_id"], "asset_version": 1}
    grant = call("memory_grant_create", {**asset, "consumer_project_id": PROJECT_ID + "-other", "expires_at": until,
                 "max_classification": "internal", "idempotency_key": uuid4().hex})
    shared_args = {"project_id": PROJECT_ID + "-other", "grant_id": grant["grant_id"], "grant_version": 1}
    shared = call("memory_shared_read", shared_args, token=CROSS_TOKEN)
    assert shared["asset"]["data"]["content"] == body["content"] and shared["cache_policy"] == "no_store"
    denied = mcp("tools/call", token=CROSS_TOKEN, params={"name": "memory_knowledge_read", "arguments": {
        "project_id": PROJECT_ID + "-other", "document_id": doc["document_id"]}})
    assert denied["isError"]
    observation = call("memory_feedback_record", {**shared_args, **asset, "usefulness": "helpful", "outcome": "not_attempted",
                       "idempotency_key": uuid4().hex}, token=CROSS_TOKEN)
    assert observation["usage"] == "reported_observation_only"
    assert call("memory_feedback_list", {})["items"] == []  # Consumer feedback is not disclosed to the owner.
    status, _, headers = request("/tools/memory_knowledge_read", token=ADMIN_TOKEN,
                                 payload={"project_id": PROJECT_ID, "document_id": doc["document_id"]})
    assert status == 200 and {key.lower(): value for key, value in headers.items()}["cache-control"] == "no-store"
    call("memory_grant_revoke", {"grant_id": grant["grant_id"], "expected_version": 1})
    assert mcp("tools/call", token=CROSS_TOKEN, params={"name": "memory_shared_read", "arguments": shared_args})["isError"]
    call("memory_knowledge_delete", {"document_id": doc["document_id"], "expected_version": 1})
    assert mcp("tools/call", token=ADMIN_TOKEN, params={"name": "memory_knowledge_read", "arguments": {
        "project_id": PROJECT_ID, "document_id": doc["document_id"]}})["isError"]
    print(json.dumps({"cross_project_explicit_reference_grant": True, "revocation_no_cached_reuse": True,
                      "reported_feedback_not_approval": True, "pushed_knowledge_erasure": True}))


if __name__ == "__main__":
    main()
