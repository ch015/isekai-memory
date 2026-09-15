"""Administrator-owned project defaults, sender overrides and capture limits."""

from fastapi.encoders import jsonable_encoder

from isekai_memory.continuity.common import conflict, eligible, event, invalid, receipt, transaction
from isekai_memory.continuity.snapshots import safe_path


def validate(body):
    active, backup = set(body["default_recipient_user_ids"]), set(body["default_backup_user_ids"])
    if active & backup:
        raise invalid("Active and backup recipient sets must not overlap")
    seen = set()
    users = active | backup
    for rule in body["sender_rules"]:
        sender = rule["from_user_id"]
        recipients, backups = set(rule["recipient_user_ids"]), set(rule["backup_user_ids"])
        if sender in seen or sender in recipients | backups or recipients & backups:
            raise invalid("Duplicate sender, self recipient or overlapping recipient roles")
        seen.add(sender)
        users.update(recipients | backups)
    for path in body["checkpoint_allowed_paths"]:
        safe_path(path)
    return users


def resolve(body, sender):
    for rule in body["sender_rules"]:
        if rule["from_user_id"] == sender:
            return rule["recipient_user_ids"], rule["backup_user_ids"]
    return body["default_recipient_user_ids"], body["default_backup_user_ids"]


async def set_policy(arguments, *, principal):
    project = arguments["project_id"]
    body = arguments["policy"]
    users = validate(body)
    async with transaction(project) as conn:
        replay = await receipt(conn, arguments, principal, "policy_set")
        if replay:
            return replay
        row = await conn.fetchrow("SELECT version FROM memory_continuity_policies WHERE project_id=$1", project)
        version = row["version"] if row else 0
        if version != arguments["expected_version"]:
            raise conflict()
        # Disabling must remain possible even after every recipient loses their token.
        if body["enabled"]:
            await eligible(conn, project, users)
        await conn.execute("INSERT INTO memory_continuity_policies(project_id,version,policy,updated_by) VALUES($1,$2,$3,$4) "
                           "ON CONFLICT(project_id) DO UPDATE SET version=EXCLUDED.version,policy=EXCLUDED.policy,"
                           "updated_by=EXCLUDED.updated_by,updated_at=clock_timestamp()", project, version + 1, body, principal.user_id)
        await event(conn, project, principal.user_id, "policy_set", project,
                    {"version": version + 1, "policy": body, "reason": arguments["reason"]})
        return await receipt(conn, arguments, principal, "policy_set", {"project_id": project, "version": version + 1})


async def get_policy(arguments, *, principal):
    async with transaction(arguments["project_id"]) as conn:
        row = await conn.fetchrow("SELECT * FROM memory_continuity_policies WHERE project_id=$1", arguments["project_id"])
        return jsonable_encoder({"configured": row is not None, "version": row["version"] if row else 0,
                                 "policy": row["policy"] if row else None, "actor_id": principal.user_id,
                                 "project_id": arguments["project_id"], "cache_policy": "no_store"})
