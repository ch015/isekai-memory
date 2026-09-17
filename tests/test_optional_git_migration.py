"""016→017 keeps IDs, roles, setup and revisions; downgrade refuses data loss."""
import json
import os
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


def test_optional_git_migration_preserves_legacy_rows():
    url = os.environ["MEMORY_TEST_DATABASE_URL"]
    name = "ade_migration_" + uuid4().hex
    parsed = urlsplit(url)
    isolated = urlunsplit(parsed._replace(path="/" + name))
    env = {**os.environ, "ISEKAI_MEMORY_DATABASE_URL": isolated}
    def migrate(revision, command="upgrade", check=True):
        return subprocess.run([sys.executable, "-m", "alembic", command, revision], env=env, capture_output=True, text=True, check=check)
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            migrate("016")
            with psycopg.connect(isolated) as conn:
                conn.execute("INSERT INTO memory_projects(project_id,organization_id,name,git_url,git_ref,owner_id,setup,revision) VALUES ('legacy','org','old','https://example.com/a.git','main','alice',%s,7)", (json.dumps({"preserved": True}),))
                conn.execute("INSERT INTO memory_project_members VALUES ('legacy','bob','write','alice')")
                before = conn.execute("SELECT * FROM memory_projects").fetchall()
                members = conn.execute("SELECT * FROM memory_project_members").fetchall()
            migrate("017")
            with psycopg.connect(isolated) as conn:
                assert conn.execute("SELECT * FROM memory_projects").fetchall() == before
                assert conn.execute("SELECT * FROM memory_project_members").fetchall() == members
                conn.execute("INSERT INTO memory_projects(project_id,organization_id,name,owner_id,setup,revision) VALUES ('document','org','doc','alice','{}',1)")
            refused = migrate("016", "downgrade", False)
            assert refused.returncode != 0 and "non-Git projects exist" in refused.stderr
            with psycopg.connect(isolated) as conn:
                assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "017"
                assert conn.execute("SELECT count(*) FROM memory_projects").fetchone()[0] == 2
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
