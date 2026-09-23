"""Align recipient eligibility with membership and retain portable handoff provenance."""

from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE handoffs ADD COLUMN compatibility_digest text
            CHECK (compatibility_digest ~ '^sha256:[0-9a-f]{64}$');
        CREATE OR REPLACE VIEW memory_eligible_members AS
        SELECT project_id,user_id,min(created_at) AS created_at FROM (
            SELECT t.project_id,t.user_id,t.created_at FROM access_tokens t
                LEFT JOIN memory_projects p ON p.project_id=t.project_id
                LEFT JOIN memory_project_members m ON m.project_id=p.project_id AND m.user_id=t.user_id
                WHERE t.revoked_at IS NULL AND (t.expires_at IS NULL OR t.expires_at>clock_timestamp())
                AND NOT ('projects'=ANY(t.scopes))
                AND ('admin'=ANY(t.scopes) OR ('read'=ANY(t.scopes) AND 'write'=ANY(t.scopes)))
                AND (p.project_id IS NULL OR p.owner_id=t.user_id OR m.role='write')
            UNION ALL
            SELECT p.project_id,t.user_id,t.created_at FROM access_tokens t
                JOIN memory_projects p ON p.owner_id=t.user_id OR EXISTS (
                    SELECT 1 FROM memory_project_members m
                    WHERE m.project_id=p.project_id AND m.user_id=t.user_id AND m.role='write')
                WHERE t.revoked_at IS NULL AND (t.expires_at IS NULL OR t.expires_at>clock_timestamp())
                AND 'projects'=ANY(t.scopes)
                AND ('admin'=ANY(t.scopes) OR ('read'=ANY(t.scopes) AND 'write'=ANY(t.scopes)))
            UNION ALL
            SELECT p.project_id,i.user_id,i.created_at FROM memory_identities i
                JOIN memory_projects p ON p.organization_id=i.organization_id
                LEFT JOIN memory_project_members m ON m.project_id=p.project_id AND m.user_id=i.user_id
                WHERE i.disabled_at IS NULL AND (p.owner_id=i.user_id OR m.role='write')
            UNION ALL
            SELECT p.project_id,i.user_id,i.created_at FROM memory_github_identities i
                JOIN memory_projects p ON p.organization_id=i.organization_id
                LEFT JOIN memory_project_members m ON m.project_id=p.project_id AND m.user_id=i.user_id
                WHERE i.disabled_at IS NULL AND (p.owner_id=i.user_id OR m.role='write')
        ) members GROUP BY project_id,user_id;
    """)


def downgrade():
    op.execute("""
        LOCK TABLE handoffs IN ACCESS EXCLUSIVE MODE;
        DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM handoffs WHERE compatibility_digest IS NOT NULL) THEN
                RAISE EXCEPTION '018 downgrade refused: portable handoff bindings exist';
            END IF;
        END $$;
        ALTER TABLE handoffs DROP COLUMN compatibility_digest;
        CREATE OR REPLACE VIEW memory_eligible_members AS
        SELECT project_id,user_id,min(created_at) AS created_at FROM (
            SELECT project_id,user_id,created_at FROM access_tokens WHERE revoked_at IS NULL
                AND (expires_at IS NULL OR expires_at>clock_timestamp())
                AND ('admin'=ANY(scopes) OR ('read'=ANY(scopes) AND 'write'=ANY(scopes)))
            UNION ALL
            SELECT p.project_id,i.user_id,i.created_at FROM memory_identities i
                JOIN memory_projects p ON p.organization_id=i.organization_id
                LEFT JOIN memory_project_members m ON m.project_id=p.project_id AND m.user_id=i.user_id
                WHERE i.disabled_at IS NULL AND (p.owner_id=i.user_id OR m.role='write')
            UNION ALL
            SELECT p.project_id,i.user_id,i.created_at FROM memory_github_identities i
                JOIN memory_projects p ON p.organization_id=i.organization_id
                LEFT JOIN memory_project_members m ON m.project_id=p.project_id AND m.user_id=i.user_id
                WHERE i.disabled_at IS NULL AND (p.owner_id=i.user_id OR m.role='write')
        ) members GROUP BY project_id,user_id;
    """)
