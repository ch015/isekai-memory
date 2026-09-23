"""Project member records: immutable work observations and explicitly shared materials."""
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE memory_project_records (
            sequence bigserial PRIMARY KEY,
            id uuid NOT NULL UNIQUE,
            project_id text NOT NULL REFERENCES memory_projects(project_id),
            actor_id text NOT NULL,
            kind text NOT NULL CHECK (kind IN ('activity','material','result')),
            title text NOT NULL,
            body text NOT NULL,
            unit_id text,
            refs jsonb NOT NULL DEFAULT '[]',
            occurred_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            payload_digest text NOT NULL,
            removed_at timestamptz,
            UNIQUE(project_id,actor_id,id)
        );
        CREATE INDEX memory_project_records_page ON memory_project_records(project_id,sequence DESC)
            WHERE removed_at IS NULL;
        CREATE INDEX memory_project_records_search ON memory_project_records USING gin
            (to_tsvector('simple',title || ' ' || body)) WHERE removed_at IS NULL;
    """)


def downgrade():
    op.execute("""
        LOCK TABLE memory_project_records IN ACCESS EXCLUSIVE MODE;
        DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM memory_project_records) THEN
                RAISE EXCEPTION '020 downgrade refused: shared project records exist';
            END IF;
        END $$;
        DROP TABLE memory_project_records;
    """)
