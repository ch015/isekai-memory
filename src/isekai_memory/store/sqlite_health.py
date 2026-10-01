"""Readiness checks for the local Memory schema, without PostgreSQL catalogs."""
import re
from importlib.resources import files


async def health_check(pool, revision):
    async with pool.acquire() as conn:
        actual = await conn.fetchval('SELECT version_num FROM alembic_version LIMIT 1')
        required = set()
        for resource in files('isekai_memory.store').joinpath('sqlite_schema').iterdir():
            if resource.name.endswith('.sql'):
                required.update(re.findall(r'CREATE (?:TABLE|VIEW|TRIGGER) (\w+)', resource.read_text()))
        rows = await conn.fetch("SELECT name FROM sqlite_master WHERE type IN ('table','view','trigger')")
        if actual != revision or required - {row['name'] for row in rows}:
            raise RuntimeError('SQLite Memory schema is incomplete or incompatible')
    return {'database': 'ok', 'schema_revision': actual, 'backend': 'sqlite'}
