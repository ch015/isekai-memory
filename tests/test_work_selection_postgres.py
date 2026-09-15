"""Opt-in M9 selection fences preserve legacy claim semantics and exact receipt recovery."""
import secrets
from uuid import uuid4

from tests.test_continuity_postgres import checkpoint, configure, publish, status
from tests.test_experience_postgres import harness as harness  # noqa: F401
from tests.test_experience_postgres import pytestmark as pytestmark


async def test_claim_selection_fences_replay_and_reassignment(harness):
    h = harness
    await configure(h)
    saved, _ = await checkpoint(h)
    published, _ = await publish(h, saved["checkpoint_id"])
    current = await status(h, published["bundle_id"])
    unit = current["units"][0]
    args = {"unit_id": unit["id"], "claim_token": secrets.token_urlsafe(32),
            "expected_generation": unit["claim_generation"], "expected_routing_version": current["bundle"]["version"]}
    await h.call("memory_continuity_claim", {**args, "expected_generation": 99}, ok=False)
    await h.call("memory_continuity_claim", {**args, "expected_routing_version": 99}, ok=False)
    first = await h.call("memory_continuity_claim", args)
    assert first["claim_generation"] == args["expected_generation"] + 1
    assert (await h.call("memory_continuity_claim", args))["replayed"]
    await h.call("memory_continuity_claim", {**args, "expected_generation": first["claim_generation"]}, ok=False)
    await h.call("memory_continuity_release", {"unit_id": unit["id"], "claim_token": args["claim_token"],
                 "claim_generation": first["claim_generation"], "action": "release", "reason": "fixture",
                 "idempotency_key": uuid4().hex})
    await h.call("memory_continuity_claim", {**args, "claim_token": secrets.token_urlsafe(32)}, ok=False)
    fresh = await h.call("memory_continuity_claim", {**args, "expected_generation": first["claim_generation"],
                         "claim_token": secrets.token_urlsafe(32)})
    assert fresh["claim_generation"] == first["claim_generation"] + 1


async def test_both_selection_fences_are_required_together(harness):
    await harness.call("memory_continuity_claim", {"unit_id": str(uuid4()), "claim_token": secrets.token_urlsafe(32),
                        "expected_generation": 0}, ok=False)
