"""Project reference records. Authentication supplies authors; writes never change work state."""
import re
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from fastapi.encoders import jsonable_encoder

from isekai_memory.retrieval.citations import canonical, digest
from isekai_memory.store.database import get_pool

from .service import fail

SECRET = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:AKIA|ASIA)[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{30,}")


def validate_content(args):
    if len(canonical(args).encode("utf-8")) > 49152:
        raise fail("Shared record exceeds the 48 KiB request budget", "MEM-RECORD-INVALID", 400)
    if not args["title"].strip() or SECRET.search(args["title"] + "\n" + args["body"]):
        raise fail("Empty title or recognizable credentials in shared content", "MEM-RECORD-INVALID", 400)
    for ref in args["refs"]:
        parsed = urlsplit(ref["uri"])
        # Relative file references are labels only; no local/remote fetching occurs here.
        if parsed.scheme:
            valid = parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password
        else:
            valid = not ref["uri"].startswith(("/", "\\")) and "\\" not in ref["uri"] and ".." not in ref["uri"].split("/")
        if not valid or any(ord(c) < 32 for c in ref["uri"]) or SECRET.search(ref["uri"]):
            raise fail("References must be relative paths or HTTPS URLs without credentials", "MEM-RECORD-INVALID", 400)


async def context(conn, args, principal):
    if args.get("expected_actor", principal.user_id) != principal.user_id:
        raise fail("Sharing account changed; keep the local pending records", "MEM-RECORD-ACTOR", 403)
    row = await conn.fetchrow("SELECT owner_id FROM memory_projects WHERE project_id=$1 FOR SHARE", args["project_id"])
    if row is None:
        raise fail("Register this project before sharing records", "MEM-RECORD-PROJECT", 404)
    # Recheck within the transaction: directory/scoped credentials have the same membership rules.
    role = "owner" if row["owner_id"] == principal.user_id else await conn.fetchval(
        "SELECT role FROM memory_project_members WHERE project_id=$1 AND user_id=$2", args["project_id"], principal.user_id)
    if role is None and not principal.local:
        raise fail()
    return role


def wire(row):
    result = dict(row)
    result["record_id"] = str(result.pop("id"))
    result["citation"] = "memory-project:" + result["record_id"]
    result.pop("removed_at", None)
    return jsonable_encoder(result)


async def put(args, principal):
    validate_content(args)
    body = {key: args.get(key) for key in ("kind", "title", "body", "unit_id", "refs")}
    hashed = digest(canonical(body))
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", args["project_id"])
        role = await context(conn, args, principal)
        if role not in {"write", "owner"} and not principal.local:
            raise fail()
        row = await conn.fetchrow("SELECT * FROM memory_project_records WHERE id=$1", UUID(args["record_id"]))
        if row:
            if row["project_id"] != args["project_id"] or row["actor_id"] != principal.user_id or row["payload_digest"] != hashed:
                raise fail("Record ID already binds different content or identity", "MEM-RECORD-CONFLICT", 409)
            return {"record_id": str(row["id"]), "payload_digest": hashed, "removed": row["removed_at"] is not None, "already_applied": True}
        await conn.execute("""INSERT INTO memory_project_records(id,project_id,actor_id,kind,title,body,unit_id,refs,occurred_at,payload_digest)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""", UUID(args["record_id"]), args["project_id"], principal.user_id,
            args["kind"], args["title"], args["body"], args.get("unit_id"), args["refs"],
            datetime.fromisoformat(args["occurred_at"].replace("Z", "+00:00")), hashed)
    return {"record_id": args["record_id"], "payload_digest": hashed, "removed": False, "already_applied": False}


async def listing(args, principal):
    query = args.get("query", "").strip()
    literal = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    limit = args.get("limit", 30)
    async with get_pool().acquire() as conn, conn.transaction():
        role = await context(conn, args, principal)
        rows = await conn.fetch("""SELECT * FROM memory_project_records WHERE project_id=$1 AND removed_at IS NULL
            AND ($2::text IS NULL OR kind=$2) AND ($3::text IS NULL OR unit_id=$3)
            AND ($4::bigint IS NULL OR sequence<$4)
            AND ($5='' OR to_tsvector('simple',title || ' ' || body) @@ plainto_tsquery('simple',$5)
                OR title ILIKE $6 OR body ILIKE $6)
            ORDER BY sequence DESC LIMIT $7""", args["project_id"], args.get("kind"), args.get("unit_id"),
            args.get("before"), query, "%" + literal + "%", limit + 1)
    writable = principal.local or bool(principal.scopes & {"write", "admin"}) and role in {"write", "owner"}
    return {"project_id": args["project_id"], "actor_id": principal.user_id, "can_share": writable,
            "can_remove_any": writable and (principal.local or role == "owner"), "items": [wire(row) for row in rows[:limit]],
            "next_cursor": rows[limit - 1]["sequence"] if len(rows) > limit else None,
            "usage": "reference_only", "cache_policy": "no_store"}


async def remove(args, principal):
    async with get_pool().acquire() as conn, conn.transaction():
        role = await context(conn, args, principal)
        row = await conn.fetchrow("SELECT * FROM memory_project_records WHERE project_id=$1 AND id=$2 FOR UPDATE",
                                  args["project_id"], UUID(args["record_id"]))
        if row is None or (row["actor_id"] != principal.user_id and role != "owner" and not principal.local):
            raise fail()
        await conn.execute("UPDATE memory_project_records SET title='',body='',refs='[]',unit_id=NULL,removed_at=COALESCE(removed_at,clock_timestamp()) WHERE id=$1", row["id"])
    return {"record_id": args["record_id"], "removed": True}


HANDLERS = {"memory_project_record_put": put, "memory_project_record_list": listing, "memory_project_record_remove": remove}
