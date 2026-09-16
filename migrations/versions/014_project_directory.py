"""User-owned/assigned project directory for ADE; no workflow State or credentials."""

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE memory_projects (
            project_id text PRIMARY KEY, organization_id text NOT NULL,
            name text NOT NULL, git_url text NOT NULL, git_ref text NOT NULL,
            owner_id text NOT NULL, setup jsonb NOT NULL,
            revision bigint NOT NULL CHECK(revision>0),
            created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_memory_projects_owner ON memory_projects(owner_id,project_id);
        CREATE TABLE memory_project_members (
            project_id text NOT NULL REFERENCES memory_projects(project_id),
            user_id text NOT NULL, role text NOT NULL CHECK(role IN ('read','write')),
            assigned_by text NOT NULL, PRIMARY KEY(project_id,user_id)
        );
        CREATE INDEX idx_memory_project_members_user ON memory_project_members(user_id,project_id);
    """)


def downgrade():
    op.execute("""
        LOCK TABLE memory_projects, memory_project_members IN ACCESS EXCLUSIVE MODE;
        DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM memory_projects) THEN
                RAISE EXCEPTION '014 downgrade refused: registered projects exist';
            END IF;
        END $$;
        DROP TABLE memory_project_members, memory_projects;
    """)
