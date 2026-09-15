"""Offline pushed-Wiki provider: explicit snapshots, CAS, drift and erasure receipts."""

from fastapi.encoders import jsonable_encoder

from isekai_memory.retrieval.citations import canonical, digest
from isekai_memory.skills.submissions import normalize
from isekai_memory.team.common import ceiling, conflict, deadline, fail, fingerprint, listing, transaction


class PushedWikiProvider:
    """No service URL, path, credentials or network client; ingestion is an admin push."""

    name = "pushed_wiki_v1"

    @staticmethod
    def snapshot(arguments):
        title, content = normalize(arguments["title"]), normalize(arguments["content"])
        calculated = digest(canonical({"title": title, "content": content}))
        if not title or not content or calculated != arguments["content_digest"]:
            raise fail("Normalized snapshot digest does not match", "MEM-TEAM-0003", 400)
        return title, content, calculated


async def sync(arguments, *, actor_id):
    title, content, content_digest = PushedWikiProvider.snapshot(arguments)
    request_digest = fingerprint({**arguments, "title": title, "content": content})
    async with transaction(arguments["project_id"]) as conn:
        old = await conn.fetchrow("""
            SELECT * FROM memory_knowledge_documents WHERE project_id=$1 AND provider=$2 AND source_key=$3
        """, arguments["project_id"], arguments["provider"], arguments["source_key"])
        expected = arguments["expected_version"]
        if old:
            receipt = await conn.fetchrow("""
                SELECT * FROM memory_knowledge_events WHERE document_id=$1 AND version=$2
            """, old["id"], expected + 1)
            if receipt and receipt["action"] == "sync" and receipt["actor_id"] == actor_id and receipt["submission_digest"] == request_digest:
                return {"document_id": str(old["id"]), "version": expected + 1, "already_applied": True}
            if old["version"] != expected:
                raise conflict()
            # Same upstream revision cannot be silently redefined or resurrected after deletion.
            if await conn.fetchval("SELECT 1 FROM memory_knowledge_events WHERE document_id=$1 AND source_revision=$2",
                                   old["id"], arguments["source_revision"]):
                raise conflict()
            ceiling(old["classification"], arguments["classification"])
        elif expected != 0:
            raise conflict()
        valid_until = await deadline(conn, arguments["valid_until"], days=7)
        if old:
            document_id = old["id"]
            await conn.execute("""
                UPDATE memory_knowledge_documents SET source_revision=$2,version=version+1,classification=$3,
                    title=$4,content=$5,content_digest=$6,status='active',valid_until=$7,updated_at=clock_timestamp()
                WHERE id=$1
            """, document_id, arguments["source_revision"], arguments["classification"], title, content, content_digest, valid_until)
        else:
            document_id = await conn.fetchval("""
                INSERT INTO memory_knowledge_documents(project_id,provider,source_key,source_revision,version,
                    classification,title,content,content_digest,status,valid_until)
                VALUES ($1,$2,$3,$4,1,$5,$6,$7,$8,'active',$9) RETURNING id
            """, arguments["project_id"], arguments["provider"], arguments["source_key"], arguments["source_revision"],
                arguments["classification"], title, content, content_digest, valid_until)
        await conn.execute("""
            INSERT INTO memory_knowledge_events(document_id,version,actor_id,action,source_revision,submission_digest)
            VALUES ($1,$2,$3,'sync',$4,$5)
        """, document_id, expected + 1, actor_id, arguments["source_revision"], request_digest)
        return {"document_id": str(document_id), "version": expected + 1, "already_applied": False}


async def delete(arguments, *, actor_id):
    async with transaction(arguments["project_id"]) as conn:
        row = await conn.fetchrow("SELECT * FROM memory_knowledge_documents WHERE id=$1::uuid AND project_id=$2",
                                  arguments["document_id"], arguments["project_id"])
        if not row:
            raise fail()
        version = arguments["expected_version"] + 1
        receipt = await conn.fetchrow("SELECT * FROM memory_knowledge_events WHERE document_id=$1 AND version=$2", row["id"], version)
        if receipt and receipt["action"] == "delete" and receipt["actor_id"] == actor_id:
            return {"document_id": str(row["id"]), "version": version, "already_applied": True}
        if row["version"] != arguments["expected_version"] or row["status"] != "active":
            raise conflict()
        await conn.execute("UPDATE memory_knowledge_documents SET title='',content='',status='deleted',version=version+1,"
                           "updated_at=clock_timestamp() WHERE id=$1", row["id"])
        await conn.execute("""
            INSERT INTO memory_knowledge_events(document_id,version,actor_id,action,submission_digest)
            VALUES ($1,$2,$3,'delete',$4)
        """, row["id"], version, actor_id, fingerprint(arguments))
        return {"document_id": str(row["id"]), "version": version, "already_applied": False}


async def get(conn, arguments):
    row = await conn.fetchrow("""
        SELECT * FROM memory_knowledge_documents WHERE id=$1::uuid AND project_id=$2 AND status='active'
            AND valid_until>clock_timestamp()
    """, arguments["document_id"], arguments["project_id"])
    if not row or ("expected_version" in arguments and row["version"] != arguments["expected_version"]):
        raise fail()
    ceiling(row["classification"], arguments.get("max_classification", "internal"))
    result = {key: value for key, value in dict(row).items() if key != "id"}
    result.update(document_id=row["id"], freshness="publisher_reported", provider_revision_verified=False)
    return jsonable_encoder(result)


async def read(arguments):
    async with transaction(arguments["project_id"]) as conn:
        return {"knowledge": await get(conn, arguments), "usage": "reference_only", "cache_policy": "no_store"}


async def list_documents(arguments):
    return await listing(arguments, table="memory_knowledge_documents", view="knowledge",
                         columns="id,provider,source_key,source_revision,version,classification,status,valid_until,created_at,updated_at")
