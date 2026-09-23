"""Separate declared workspace source from optional Git clone coordinates."""

from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE memory_projects ADD COLUMN source_kind text NOT NULL DEFAULT 'unknown'
            CHECK (source_kind IN ('git','directory','unknown'));
        UPDATE memory_projects SET source_kind='git' WHERE git_url IS NOT NULL;
        ALTER TABLE memory_projects ADD CONSTRAINT memory_projects_source_git
            CHECK (git_url IS NULL OR source_kind='git');
    """)


def downgrade():
    op.execute("""
        LOCK TABLE memory_projects IN ACCESS EXCLUSIVE MODE;
        DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM memory_projects WHERE git_url IS NULL AND source_kind<>'unknown') THEN
                RAISE EXCEPTION '019 downgrade refused: explicit project source metadata exists';
            END IF;
        END $$;
        ALTER TABLE memory_projects DROP CONSTRAINT memory_projects_source_git;
        ALTER TABLE memory_projects DROP COLUMN source_kind;
    """)
