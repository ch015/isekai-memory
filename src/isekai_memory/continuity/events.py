"""Read-only durable catch-up with commit-ordered heads and encrypted scope-bound cursors.

Notification retention is separate from immutable M8 audit. No source bodies, raw details,
capabilities, hidden sequence counters, or arbitrary actor fields are returned.
"""
import base64
import hashlib
import hmac
import struct
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from fastapi.encoders import jsonable_encoder

from isekai_memory.continuity.common import CLASSIFICATIONS, canonical, event, fail, invalid, receipt, transaction
from isekai_memory.continuity.overview import read_transaction
from isekai_memory.server.auth import authorize_tool

RETENTION_SECONDS = 7 * 86400
MAX_EVENTS = 50000
PURGE_BATCH = 200
TOPICS = ("checkpoint_saved", "handover_changed", "intake_acknowledged", "work_claimed", "work_released",
          "work_completed", "access_changed", "policy_changed", "session_registered", "session_state_changed",
          "session_ended", "usage_finalized", "maintenance")


def binding(arguments, principal):
    return hashlib.sha256(canonical(["collaboration-events-v1", arguments["project_id"], principal.user_id,
        sorted(principal.scopes), principal.local, arguments.get("scope", "mine"),
        arguments.get("max_classification", "internal")])).digest()


def encode_cursor(secret, scope, position):
    # Fixed-size plaintext hides even the number of digits in an unauthorized global counter.
    body = struct.pack(">B32sQ", 1, scope, position)
    return Fernet(base64.urlsafe_b64encode(secret)).encrypt(body).decode("ascii")


def decode_cursor(secret, scope, cursor, now):
    codec = Fernet(base64.urlsafe_b64encode(secret))
    try:
        plain = codec.decrypt(cursor.encode("ascii"))
        version, encoded_scope, position = struct.unpack(">B32sQ", plain)
        if version != 1 or not hmac.compare_digest(scope, encoded_scope):
            raise invalid("Event cursor belongs to another identity or filter; start a fresh full refresh")
        issued = codec.extract_timestamp(cursor.encode("ascii"))
        if issued > now.timestamp() + 60 or now.timestamp() - issued > RETENTION_SECONDS:
            return None, "cursor_expired"
        return position, None
    except (InvalidToken, UnicodeError, ValueError, struct.error):
        # Key rotation, database restore, or corrupt token: authenticated caller must resync.
        return None, "cursor_unusable"


async def _purge(conn, project, now):
    head = await conn.fetchrow("SELECT position,pruned_through FROM memory_event_heads WHERE project_id=$1 FOR UPDATE", project)
    if head is None:
        return 0
    rows = await conn.fetch("""
        DELETE FROM memory_collaboration_events WHERE (project_id,position) IN (
            SELECT project_id,position FROM memory_collaboration_events
            WHERE project_id=$1 AND (created_at<$2 OR position<=$3)
            ORDER BY position LIMIT $4
        ) RETURNING position
    """, project, now - timedelta(seconds=RETENTION_SECONDS), max(0, head["position"] - MAX_EVENTS), PURGE_BATCH)
    if rows:
        await conn.execute("UPDATE memory_event_heads SET pruned_through=greatest(pruned_through,$2) WHERE project_id=$1",
                           project, max(row["position"] for row in rows))
    return len(rows)


async def append(conn, project, topic, resource_kind, resource_id, classification, audience, *, revision=None, broadcast=False):
    if topic not in TOPICS or classification not in CLASSIFICATIONS:
        raise invalid("Unsupported notification projection")
    audience = sorted(set(audience))
    if len(audience) > 128:
        raise invalid("Notification audience exceeds the project handover limit")
    # This row lock is held until the source transaction commits. A concurrent writer cannot
    # reserve a later visible position while an earlier transaction remains uncommitted.
    position = await conn.fetchval("""
        INSERT INTO memory_event_heads(project_id,position) VALUES($1,1)
        ON CONFLICT(project_id) DO UPDATE SET position=memory_event_heads.position+1 RETURNING position
    """, project)
    await conn.execute("""
        INSERT INTO memory_collaboration_events(project_id,position,topic,resource_kind,resource_id,
                                                classification,audience,revision,broadcast)
        VALUES($1,$2,$3,$4,$5::uuid,$6,$7,$8,$9)
    """, project, position, topic, resource_kind, resource_id, classification, audience, revision, broadcast)
    await _purge(conn, project, await conn.fetchval("SELECT clock_timestamp()"))


async def project_event(conn, project, actor, action, target, details):
    """Whitelist projections of existing transaction-local audit events, never serialize details."""
    if action in {"policy_set", "presence_policy_set", "usage_policy_set"}:
        await append(conn, project, "policy_changed", "signal", None, "public", [], revision=details["version"], broadcast=True)
    elif action in {"checkpoint_save", "checkpoint_forget"}:
        row = await conn.fetchrow("SELECT from_user,classification,version FROM memory_checkpoints WHERE project_id=$1 AND id=$2::uuid", project, str(target))
        if row:
            erased = action == "checkpoint_forget"
            await append(conn, project, "access_changed" if erased else "checkpoint_saved",
                         "signal" if erased else "checkpoint", None if erased else str(target), row["classification"],
                         [row["from_user"], *details.get("revoked_user_ids", [])] if erased else [row["from_user"]], revision=row["version"])
    elif action in {"publish", "reassign", "ack", "claim", "work_release", "work_complete"}:
        row = await conn.fetchrow("SELECT from_user,classification,version FROM memory_continuity_bundles WHERE project_id=$1 AND id=$2::uuid", project, str(target))
        if row:
            active = await conn.fetch("SELECT recipient_user_id FROM memory_continuity_deliveries WHERE project_id=$1 AND bundle_id=$2::uuid AND revoked_at IS NULL", project, str(target))
            users = [item["recipient_user_id"] for item in active]
            topics = {"ack": "intake_acknowledged", "claim": "work_claimed", "work_release": "work_released", "work_complete": "work_completed"}
            await append(conn, project, topics.get(action, "handover_changed"), "bundle", str(target), row["classification"],
                         [row["from_user"], *users], revision=details.get("claim_generation", row["version"]))
            if action == "reassign":
                removed = set(details.get("old_recipient_user_ids", [])) - set(users)
                if removed:
                    await append(conn, project, "access_changed", "signal", None, row["classification"], removed)
    elif action in {"presence_register", "presence_state", "presence_end"}:
        row = await conn.fetchrow("SELECT actor_id,classification,sequence FROM memory_presence_sessions WHERE project_id=$1 AND id=$2::uuid", project, str(target))
        if row:
            topic = {"presence_register": "session_registered", "presence_state": "session_state_changed", "presence_end": "session_ended"}[action]
            await append(conn, project, topic, "presence", str(target), row["classification"], [row["actor_id"]], revision=max(1, row["sequence"]))
            previous = details.get("previous_classification", row["classification"])
            if previous != row["classification"]:
                await append(conn, project, "access_changed", "signal", None, previous, [row["actor_id"]])
    elif action == "usage_finalized":
        row = await conn.fetchrow("SELECT actor_id,classification,sequence FROM memory_usage_sessions WHERE project_id=$1 AND id=$2::uuid", project, str(target))
        if row:
            await append(conn, project, "usage_finalized", "usage", str(target), row["classification"], [row["actor_id"]], revision=row["sequence"])
    elif action in {"presence_prune", "usage_prune"}:
        await append(conn, project, "maintenance", "signal", None, "public", [actor])


VISIBLE = """
    e.project_id=$1 AND e.position>$2 AND e.position<=$3 AND e.classification=ANY($4::text[])
    AND (e.broadcast OR $5::boolean OR $6=ANY(e.audience))
    AND e.created_at>=$7::timestamptz-interval '7 days'
    AND (
        e.resource_kind='signal' OR
        (e.resource_kind='checkpoint' AND EXISTS(
            SELECT 1 FROM memory_checkpoints c WHERE c.project_id=e.project_id AND c.id=e.resource_id
              AND c.classification=ANY($4::text[]) AND c.forgotten_at IS NULL AND c.expires_at>$7
              AND ($5::boolean OR c.from_user=$6))) OR
        (e.resource_kind='bundle' AND EXISTS(
            SELECT 1 FROM memory_continuity_bundles b WHERE b.project_id=e.project_id AND b.id=e.resource_id
              AND b.classification=ANY($4::text[]) AND b.revoked_at IS NULL AND b.expires_at>$7
              AND ($5::boolean OR b.from_user=$6 OR EXISTS(
                  SELECT 1 FROM memory_continuity_deliveries d WHERE d.project_id=b.project_id AND d.bundle_id=b.id
                    AND d.recipient_user_id=$6 AND d.revoked_at IS NULL)))) OR
        (e.resource_kind='presence' AND EXISTS(
            SELECT 1 FROM memory_presence_sessions p WHERE p.project_id=e.project_id AND p.id=e.resource_id
              AND p.classification=ANY($4::text[]) AND p.retired_at IS NULL AND ($5::boolean OR p.actor_id=$6))) OR
        (e.resource_kind='usage' AND EXISTS(
            SELECT 1 FROM memory_usage_sessions u WHERE u.project_id=e.project_id AND u.id=e.resource_id
              AND u.classification=ANY($4::text[]) AND u.retired_at IS NULL AND ($5::boolean OR u.actor_id=$6)))
    )
"""


async def listing(arguments, *, principal):
    authorize_tool(principal, "memory_collaboration_events", arguments)
    from isekai_memory.continuity.common import is_admin
    project = arguments["project_id"]
    scope = {"kind": arguments.get("scope", "mine"), "max_classification": arguments.get("max_classification", "internal")}
    if scope["kind"] == "project" and not is_admin(principal):
        raise fail("Project event scope requires administrator authority", "MEM-COLLABORATION-0001", 403)
    levels = CLASSIFICATIONS[:CLASSIFICATIONS.index(scope["max_classification"]) + 1]
    async with read_transaction() as conn:
        now = await conn.fetchval("SELECT transaction_timestamp()")
        secret = await conn.fetchval("SELECT secret FROM memory_event_cursor_key WHERE singleton=1")
        head = await conn.fetchrow("SELECT position,pruned_through FROM memory_event_heads WHERE project_id=$1", project)
        high, low = (head["position"], head["pruned_through"]) if head else (0, 0)
        bound = binding(arguments, principal)
        expired = await conn.fetchval("SELECT max(position) FROM memory_collaboration_events "
            "WHERE project_id=$1 AND created_at<$2::timestamptz-interval '7 days'", project, now)
        low = max(low, expired or 0)
        cursor = arguments.get("cursor")
        position, reason = decode_cursor(secret, bound, cursor, now) if cursor else (None, "initial")
        if position is not None and (position < low or position > high):
            position, reason = None, "retention_gap" if position < low else "cursor_ahead"
        rows = []
        if position is not None:
            rows = await conn.fetch(f"""
                SELECT e.id,e.position,e.topic,e.resource_id AS target_id,e.classification,e.revision,e.created_at AS occurred_at
                FROM memory_collaboration_events e WHERE {VISIBLE} ORDER BY e.position LIMIT $8
            """, project, position, high, levels, scope["kind"] == "project", principal.user_id, now, arguments.get("limit", 50) + 1)
        more = len(rows) > arguments.get("limit", 50)
        rows = rows[:arguments.get("limit", 50)]
        next_position = rows[-1]["position"] if more else high
        items = [{key: value for key, value in dict(row).items() if key != "position"} for row in rows]
        return jsonable_encoder({"contract_version": 1, "project_id": project, "actor_id": principal.user_id,
            "scope": scope, "observed_at": now, "cache_policy": "no_store", "items": items, "has_more": more,
            "next_cursor": encode_cursor(secret, bound, next_position), "reset_required": position is None,
            "reset_reason": reason, "retention_seconds": RETENTION_SECONDS, "ordering": "project_commit_order"})


async def prune(arguments, *, principal):
    authorize_tool(principal, "memory_collaboration_events_prune", arguments)
    async with transaction(arguments["project_id"]) as conn:
        replay = await receipt(conn, arguments, principal, "events_prune")
        if replay:
            return replay
        removed = await _purge(conn, arguments["project_id"], await conn.fetchval("SELECT clock_timestamp()"))
        await event(conn, arguments["project_id"], principal.user_id, "events_prune", arguments["project_id"],
                    {"pruned": removed, "reason": arguments["reason"]})
        return await receipt(conn, arguments, principal, "events_prune", {"project_id": arguments["project_id"],
                             "pruned": removed, "audit_erased": False})
