"""Replayable review and atomic active-version replacement."""

from isekai_memory.experience.persistence import lock_project
from isekai_memory.skills import sources
from isekai_memory.skills.sources import fail
from isekai_memory.store.database import get_pool


async def transition(conn, row, actor, action, after):
    await conn.execute("""
        UPDATE memory_skill_revisions SET status=$2,version=version+1,updated_at=clock_timestamp(),
            body=CASE WHEN $2='forgotten' THEN '{}'::jsonb ELSE body END,
            approved_at=CASE WHEN $2='active' THEN clock_timestamp() ELSE approved_at END WHERE id=$1
    """, row["id"], after)
    await conn.execute("""
        INSERT INTO memory_skill_events(revision_id,version,actor_id,action,previous_status,applied_status)
        VALUES ($1,$2,$3,$4,$5,$6)
    """, row["id"], row["version"] + 1, actor, action, row["status"], after)


async def review(arguments, *, actor_id):
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL statement_timeout='5s'")
        await lock_project(conn, arguments["project_id"])
        row = await conn.fetchrow("SELECT * FROM memory_skill_revisions WHERE id=$1::uuid AND project_id=$2 FOR UPDATE",
                                  arguments["revision_id"], arguments["project_id"])
        if row is None:
            raise fail(status=404)
        action, expected = arguments["action"], arguments["expected_version"]
        event = await conn.fetchrow("SELECT * FROM memory_skill_events WHERE revision_id=$1 AND version=$2",
                                   row["id"], expected + 1)
        if event and event["actor_id"] == actor_id and event["action"] == action:
            return {"revision_id": str(row["id"]), "applied_version": event["version"],
                    "applied_status": event["applied_status"], "already_applied": True}
        before = {"approve": "pending", "reject": "pending", "archive": "active"}.get(action)
        if row["version"] != expected or row["status"] == "forgotten" or (before and row["status"] != before):
            raise fail("Skill review version or state conflicts", "MEM-SKILL-0004")
        skill = await conn.fetchrow("SELECT * FROM memory_skills WHERE id=$1 FOR UPDATE", row["skill_id"])
        if action == "approve":
            if row["origin"] != "manual":
                raise fail("Generated scaffolds require a manual revision before approval", "MEM-SKILL-0005")
            fresh, _ = await sources.freshness(conn, row, await sources.saved(conn, row))
            if not fresh:
                raise fail()
            if row["base_active_revision"] != skill["active_revision"]:
                raise fail("The captured active Skill revision changed", "MEM-SKILL-0004")
            if skill["active_revision"] is not None:
                parent = await conn.fetchrow("SELECT * FROM memory_skill_revisions WHERE skill_id=$1 AND revision=$2 FOR UPDATE",
                                             skill["id"], skill["active_revision"])
                await transition(conn, parent, actor_id, "supersede", "superseded")
            await conn.execute("UPDATE memory_skills SET active_revision=$2 WHERE id=$1", skill["id"], row["revision"])
        elif skill["active_revision"] == row["revision"]:
            await conn.execute("UPDATE memory_skills SET active_revision=NULL WHERE id=$1", skill["id"])
        after = {"approve": "active", "reject": "rejected", "archive": "archived", "forget": "forgotten"}[action]
        await transition(conn, row, actor_id, action, after)
        return {"revision_id": str(row["id"]), "applied_version": row["version"] + 1,
                "applied_status": after, "already_applied": False}
