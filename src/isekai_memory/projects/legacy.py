"""Protect pre-directory project IDs from being claimed through global registration."""

import re

from isekai_memory.server.errors import MemoryToolError


async def require_unclaimed_or_admin(conn, principal, project_id):
    """Only a project-scoped admin can adopt existing data; global projects tokens create new namespaces."""
    if principal.local or ("projects" not in principal.scopes and "admin" in principal.scopes):
        return
    # Discover project-bearing tables from the trusted migrated schema. This covers retained
    # data even after a token expires and future tables added by migrations. Registration is rare.
    if getattr(conn, 'backend', None) == 'sqlite':
        columns = await conn.fetch("""SELECT m.name AS table_name,p.name AS column_name
            FROM sqlite_master m JOIN pragma_table_info(m.name) p
            WHERE m.type IN ('table','view') AND p.name IN ('project_id','consumer_project_id')
            ORDER BY m.name,p.name""")
    else:
        columns = await conn.fetch("""SELECT table_name,column_name FROM information_schema.columns
        WHERE table_schema=current_schema() AND column_name IN ('project_id','consumer_project_id')
        ORDER BY table_name,column_name""")
    for row in columns:
        table, column = row["table_name"], row["column_name"]
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", table):
            raise RuntimeError("Unexpected project table identifier")
        if await conn.fetchval(f'SELECT EXISTS(SELECT 1 FROM "{table}" WHERE "{column}"=$1)', project_id):
            raise MemoryToolError(
                "Existing project namespace requires registration by its project-scoped administrator",
                data={"error_code": "MEM-PROJECT-LEGACY"},
                http_status=403,
            )
