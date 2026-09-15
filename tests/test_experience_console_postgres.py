"""M9 metadata queue uses server-side classification and actor-bound cursors."""
from tests.test_experience_postgres import harness, pytestmark  # noqa: F401


async def test_metadata_queue_excludes_bodies_and_filters_before_limit(harness):  # noqa: F811
    h = harness
    first, _ = await h.propose(content="PRIVATE body 1")
    second, _ = await h.propose(content="PRIVATE body 2")
    source = await h.source("restricted")
    hidden, _ = await h.propose(source["handoff_id"], content="RESTRICTED private body")
    args = {"metadata_only": True, "max_classification": "internal", "limit": 1}
    page = await h.call("memory_experience_list", args)
    assert page["actor_id"] == "admin" and page["cache_policy"] == "no_store"
    assert page["metadata_only"] and page["has_more"]
    assert page["items"][0]["memory_id"] == second["memory_id"]
    assert not {"content", "source", "tags"} & set(page["items"][0])
    assert "PRIVATE" not in str(page) and "RESTRICTED" not in str(page)
    next_page = await h.call("memory_experience_list", {**args, "cursor": page["next_cursor"]})
    assert next_page["items"][0]["memory_id"] == first["memory_id"] and not next_page["has_more"]
    for options, role in (({"max_classification": "restricted"}, "admin"),
                          ({"metadata_only": False}, "admin"), ({}, "admin2")):
        await h.call("memory_experience_list", {**args, **options, "cursor": page["next_cursor"]}, role=role, ok=False)
    detail = await h.call("memory_experience_list", {**args, "metadata_only": False, "memory_id": first["memory_id"]})
    assert detail["items"][0]["content"] == "PRIVATE body 1" and detail["items"][0]["source"]
    assert (await h.call("memory_experience_list", {**args, "memory_id": hidden["memory_id"]}))["items"] == []
    await h.call("memory_experience_list", args, role="writer", ok=False)
