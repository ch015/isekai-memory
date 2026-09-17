"""Entra identity bindings and authenticated collaboration membership."""

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE memory_identities (
            tenant_id text NOT NULL, object_id text NOT NULL,
            user_id text NOT NULL UNIQUE, organization_id text NOT NULL,
            disabled_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(tenant_id,object_id)
        );
        CREATE VIEW memory_eligible_members AS
        SELECT project_id,user_id,min(created_at) AS created_at FROM (
            SELECT project_id,user_id,created_at FROM access_tokens WHERE revoked_at IS NULL
                AND (expires_at IS NULL OR expires_at>clock_timestamp())
                AND ('admin'=ANY(scopes) OR ('read'=ANY(scopes) AND 'write'=ANY(scopes)))
            UNION ALL
            SELECT p.project_id,i.user_id,i.created_at FROM memory_identities i
                JOIN memory_projects p ON p.organization_id=i.organization_id
                LEFT JOIN memory_project_members m ON m.project_id=p.project_id AND m.user_id=i.user_id
                WHERE i.disabled_at IS NULL AND (p.owner_id=i.user_id OR m.role='write')
        ) members GROUP BY project_id,user_id;
    """)


def downgrade():
    op.execute("DROP VIEW memory_eligible_members; DROP TABLE memory_identities;")
