"""asyncpg connection pool lifecycle management."""

from __future__ import annotations

import json

import asyncpg

from isekai_memory.config import Settings

EXPECTED_SCHEMA_REVISION = "014"
_pool: asyncpg.Pool | None = None


async def _configure_connection(connection: asyncpg.Connection) -> None:
    for type_name in ("json", "jsonb"):
        await connection.set_type_codec(
            type_name,
            schema="pg_catalog",
            encoder=lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
            decoder=json.loads,
            format="text",
        )


async def init_pool(settings: Settings) -> asyncpg.Pool:
    """Create and cache the connection pool. Idempotent."""
    global _pool
    if _pool is not None:
        return _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        init=_configure_connection,
    )
    return _pool


async def close_pool() -> None:
    """Gracefully close the pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Return the active pool. Raises if not initialized."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialized. Call init_pool() first.")
    return _pool


async def health_check() -> dict[str, str]:
    """Check connectivity, required tables, and the expected Alembic revision."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if await conn.fetchval("SELECT 1") != 1:
            raise RuntimeError("database connectivity check failed")
        has_version_table = await conn.fetchval("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        if not has_version_table:
            raise RuntimeError("database schema is not initialized")
        revision = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
        required_tables = await conn.fetchval(
            """
            SELECT bool_and(to_regclass(name) IS NOT NULL)
            FROM unnest(ARRAY[
                'public.artifacts',
                'public.artifact_policies',
                'public.handoffs',
                'public.handoff_claim_receipts',
                'public.access_tokens',
                'public.memory_projects',
                'public.memory_project_members',
                'public.memory_experiences',
                'public.memory_experience_events',
                'public.memory_experience_suppressions',
                'public.memory_generation_jobs',
                'public.memory_generation_attempts',
                'public.memory_summary_snapshots',
                'public.memory_skills',
                'public.memory_skill_revisions',
                'public.memory_skill_sources',
                'public.memory_skill_events',
                'public.memory_asset_grants',
                'public.memory_knowledge_documents',
                'public.memory_knowledge_events',
                'public.memory_skill_imports',
                'public.memory_asset_feedback',
                'public.memory_continuity_policies',
                'public.memory_checkpoints',
                'public.memory_continuity_bundles',
                'public.memory_continuity_deliveries',
                'public.memory_continuity_units',
                'public.memory_continuity_claims',
                'public.memory_continuity_events',
                'public.memory_continuity_receipts',
                'public.memory_presence_policies',
                'public.memory_presence_sessions',
                'public.memory_usage_policies',
                'public.memory_usage_sessions',
                'public.memory_usage_receipts',
                'public.memory_event_cursor_key',
                'public.memory_event_heads',
                'public.memory_collaboration_events'
            ]) AS name
            """
        )
    if revision != EXPECTED_SCHEMA_REVISION or not required_tables:
        raise RuntimeError(f"database schema revision mismatch: expected {EXPECTED_SCHEMA_REVISION}, got {revision}")
    return {"database": "ok", "schema_revision": revision}
