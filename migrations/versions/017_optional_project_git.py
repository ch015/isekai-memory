"""Allow work projects without a Git resource, preserving every existing directory row."""
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE memory_projects ALTER COLUMN git_url DROP NOT NULL;
        ALTER TABLE memory_projects ALTER COLUMN git_ref DROP NOT NULL;
        ALTER TABLE memory_projects ADD CONSTRAINT memory_projects_git_pair
            CHECK ((git_url IS NULL) = (git_ref IS NULL));
    """)


def downgrade():
    op.execute("""
        LOCK TABLE memory_projects IN ACCESS EXCLUSIVE MODE;
        DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM memory_projects WHERE git_url IS NULL) THEN
                RAISE EXCEPTION '017 downgrade refused: non-Git projects exist';
            END IF;
        END $$;
        ALTER TABLE memory_projects DROP CONSTRAINT memory_projects_git_pair;
        ALTER TABLE memory_projects ALTER COLUMN git_url SET NOT NULL;
        ALTER TABLE memory_projects ALTER COLUMN git_ref SET NOT NULL;
    """)
