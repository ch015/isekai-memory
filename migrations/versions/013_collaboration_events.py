"""Add bounded durable collaboration notifications without altering M8 audit/provenance."""
import secrets

import sqlalchemy as sa
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE memory_event_cursor_key (
            singleton smallint PRIMARY KEY CHECK(singleton=1),
            secret bytea NOT NULL CHECK(octet_length(secret)=32)
        );
        CREATE TABLE memory_event_heads (
            project_id text PRIMARY KEY, position bigint NOT NULL CHECK(position>=0),
            pruned_through bigint NOT NULL DEFAULT 0 CHECK(pruned_through>=0 AND pruned_through<=position)
        );
        CREATE TABLE memory_collaboration_events (
            project_id text NOT NULL REFERENCES memory_event_heads(project_id),
            position bigint NOT NULL CHECK(position>0), id uuid NOT NULL DEFAULT gen_random_uuid(),
            topic text NOT NULL, resource_kind text NOT NULL CHECK(resource_kind IN ('signal','checkpoint','bundle','presence','usage')),
            resource_id uuid, classification text NOT NULL CHECK(classification IN ('public','internal','confidential','restricted')),
            audience text[] NOT NULL CHECK(cardinality(audience)<=128), broadcast boolean NOT NULL DEFAULT false,
            revision bigint CHECK(revision>0), created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY(project_id,position), UNIQUE(id),
            CHECK((resource_kind='signal')=(resource_id IS NULL))
        );
        CREATE INDEX idx_collaboration_event_retention ON memory_collaboration_events(project_id,created_at,position);
    """)
    op.get_bind().execute(sa.text("INSERT INTO memory_event_cursor_key(singleton,secret) VALUES(1,:secret)"),
                          {"secret": secrets.token_bytes(32)})


def downgrade():
    op.execute("""
        LOCK TABLE memory_event_heads, memory_collaboration_events, memory_event_cursor_key IN ACCESS EXCLUSIVE MODE;
        DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM memory_event_heads WHERE position>0) THEN
                RAISE EXCEPTION '013 downgrade refused: durable notification history exists';
            END IF;
        END $$;
        DROP TABLE memory_collaboration_events, memory_event_heads, memory_event_cursor_key;
    """)
