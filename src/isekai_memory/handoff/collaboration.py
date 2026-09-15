"""Multi-user delivery views; none of these reads consume or execute work."""

from datetime import UTC, datetime

from fastapi.encoders import jsonable_encoder

from isekai_memory.experience import pagination
from isekai_memory.handoff import collaboration_store as store
from isekai_memory.handoff.service import _claim_token_digest
from isekai_memory.server.errors import MemoryToolError

CLASSIFICATIONS = ["public", "internal", "confidential", "restricted"]


def _classifications(arguments):
    ceiling = arguments.get("max_classification", "internal")
    return CLASSIFICATIONS[:CLASSIFICATIONS.index(ceiling) + 1]


def delivery_state(row, now):
    if row.get("continuity_managed", False):
        return "continuity_managed"
    if row["status"] == "acknowledged":
        return "acknowledged"
    if row["expires_at"] is None or row["expires_at"] <= now or row["status"] == "expired":
        return "expired"
    if row["status"] == "pending":
        return "available"
    if row["claim_lease_expires_at"] is None:
        return "legacy_claimed"
    return "leased" if row["claim_lease_expires_at"] > now else "lease_expired"


def _metadata(row, observed_at, actor_id):
    result = dict(row)
    result.pop("observed_at", None)
    result["handoff_id"] = str(result.pop("id"))
    result["delivery_state"] = delivery_state(row, observed_at)
    result["can_claim"] = (result["delivery_state"] in {"available", "lease_expired"}
                           and row["recipient_user_id"] in (None, actor_id))
    result["lease_expires_at"] = result.pop("claim_lease_expires_at")
    return jsonable_encoder(result)


async def inbox(arguments, *, actor_id):
    view = arguments.get("view", "available")
    scope = ["handoff-inbox-v1", arguments["project_id"], actor_id, view,
             arguments.get("unit_id", ""), arguments.get("max_classification", "internal")]
    try:
        before_at, before_id = pagination.decode(arguments.get("cursor"), scope)
    except MemoryToolError as exc:
        raise MemoryToolError(
            "Invalid inbox cursor for this project, actor and view",
            data={"error_code": "MEM-HANDOFF-0009"}, http_status=400,
        ) from exc
    limit = arguments.get("limit", 20)
    rows, observed_at = await store.inbox_rows(
        project_id=arguments["project_id"], actor_id=actor_id, view=view,
        unit_id=arguments.get("unit_id"), classifications=_classifications(arguments),
        before_at=before_at, before_id=before_id, limit=limit,
    )
    result = pagination.page(rows, limit, scope)
    result["items"] = [_metadata(row, observed_at, actor_id) for row in result["items"]]
    result.update(observed_at=observed_at.isoformat(), view=view, cache_policy="no_store")
    return result


async def status(arguments, *, actor_id):
    row = await store.status_row(
        project_id=arguments["project_id"], handoff_id=arguments["handoff_id"],
        classifications=_classifications(arguments),
    )
    if row is None:
        raise MemoryToolError(
            "Handoff is not available in this project and classification view",
            data={"error_code": "MEM-HANDOFF-0001"}, http_status=404,
        )
    return {"handoff": _metadata(row, row["observed_at"], actor_id),
            "observed_at": row["observed_at"].isoformat(), "cache_policy": "no_store"}


async def renew(arguments, *, actor_id, settings):
    deadline = datetime.fromisoformat(arguments["lease_expires_at"].upper().replace("Z", "+00:00")).astimezone(UTC)
    return await store.renew_lease(
        project_id=arguments["project_id"], handoff_id=arguments["handoff_id"], actor_id=actor_id,
        token_digest=_claim_token_digest(arguments["claim_token"]), generation=arguments["claim_generation"],
        deadline=deadline, max_seconds=settings.handoff_claim_lease_max_seconds,
    )
