"""018 preserves legacy payloads and refuses to erase portable bindings."""

import os
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


def test_multiuser_migration_preserves_rows_and_fences_downgrade():
    url = os.environ["MEMORY_TEST_DATABASE_URL"]
    name = "sharing_migration_" + uuid4().hex
    isolated = urlunsplit(urlsplit(url)._replace(path="/" + name))
    env = {**os.environ, "ISEKAI_MEMORY_DATABASE_URL": isolated}

    def migrate(revision, command="upgrade", check=True):
        return subprocess.run([sys.executable, "-m", "alembic", command, revision],
                              env=env, capture_output=True, text=True, check=check)

    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            migrate("017")
            with psycopg.connect(isolated) as conn:
                conn.execute("""INSERT INTO handoffs(project_id,unit_id,phase_attempt_id,phase_id,from_user,
                    result_status,task_envelope,result_envelope,context_digest,lock_snapshot_digest,
                    envelope_digest,payload_digest) VALUES
                    ('legacy','unit','attempt','phase','alice','succeeded','{}','{}','ctx','lock','env','payload')""")
                before = conn.execute("SELECT to_jsonb(h) FROM handoffs h").fetchone()[0]
            migrate("018")
            with psycopg.connect(isolated) as conn:
                row = conn.execute("SELECT to_jsonb(h) FROM handoffs h").fetchone()[0]
                assert row.pop("compatibility_digest") is None
                assert row == before
            migrate("017", "downgrade")
            with psycopg.connect(isolated) as conn:
                assert conn.execute("SELECT to_jsonb(h) FROM handoffs h").fetchone()[0] == before
            migrate("018")
            with psycopg.connect(isolated) as conn:
                conn.execute("UPDATE handoffs SET compatibility_digest=%s", ("sha256:" + "a" * 64,))
            refused = migrate("017", "downgrade", False)
            assert refused.returncode != 0 and "portable handoff bindings exist" in refused.stderr
            with psycopg.connect(isolated) as conn:
                assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "018"
                assert conn.execute("SELECT compatibility_digest FROM handoffs").fetchone()[0] == "sha256:" + "a" * 64
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
