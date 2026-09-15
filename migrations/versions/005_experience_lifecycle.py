"""Immutable revisions, suppression, validity and content erasure.

Revision ID: 005
Revises: 004
"""

import hashlib
import unicodedata

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memory_experiences", sa.Column("source_payload_digest", sa.Text()))
    op.add_column("memory_experiences", sa.Column("content_fingerprint", sa.Text()))
    op.add_column("memory_experiences", sa.Column("valid_from", sa.DateTime(timezone=True)))
    op.add_column("memory_experiences", sa.Column("supersedes_id", UUID()))
    op.add_column("memory_experiences", sa.Column("supersedes_version", sa.Integer()))
    op.add_column("memory_experiences", sa.Column("revision_root_id", UUID()))
    op.add_column("memory_experiences", sa.Column("revision_number", sa.Integer(), server_default="1", nullable=False))
    op.add_column(
        "memory_experiences", sa.Column("is_correction", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    # Frozen v1 fingerprint algorithm; migrations never import mutable service code.
    bind = op.get_bind()
    after = None
    while (
        rows := bind.execute(
            sa.text(
                "SELECT id, kind, content, source FROM memory_experiences "
                "WHERE CAST(:after AS uuid) IS NULL OR id > CAST(:after AS uuid) ORDER BY id LIMIT 500"
            ),
            {"after": after},
        )
        .mappings()
        .all()
    ):
        for row in rows:
            body = " ".join(unicodedata.normalize("NFKC", row["content"]).casefold().split())
            fingerprint = "sha256:" + hashlib.sha256((row["kind"] + "\n" + body).encode()).hexdigest()
            bind.execute(
                sa.text(
                    "UPDATE memory_experiences SET content_fingerprint=:fingerprint, source_payload_digest=:digest WHERE id=:id"
                ),
                {"id": row["id"], "fingerprint": fingerprint, "digest": row["source"]["payload_digest"]},
            )
        after = rows[-1]["id"]
    op.alter_column("memory_experiences", "source_payload_digest", nullable=False)
    op.alter_column("memory_experiences", "content_fingerprint", nullable=False)
    op.alter_column("memory_experiences", "source_handoff_id", nullable=True)
    op.create_unique_constraint("uq_experience_id_project", "memory_experiences", ["id", "project_id"])
    for column in ("supersedes_id", "revision_root_id"):
        op.create_foreign_key(
            "fk_experience_" + column,
            "memory_experiences",
            "memory_experiences",
            [column, "project_id"],
            ["id", "project_id"],
            ondelete="RESTRICT",
        )
    op.drop_constraint("ck_experience_status", "memory_experiences", type_="check")
    op.create_check_constraint(
        "ck_experience_status",
        "memory_experiences",
        "status IN ('pending','active','rejected','archived','superseded','forgotten')",
    )
    op.create_check_constraint(
        "ck_experience_revision",
        "memory_experiences",
        "(supersedes_id IS NULL AND supersedes_version IS NULL AND revision_root_id IS NULL AND revision_number=1 AND NOT is_correction) OR "
        "(supersedes_id IS NOT NULL AND supersedes_id<>id AND supersedes_version IS NOT NULL AND supersedes_version>=1 AND revision_root_id IS NOT NULL "
        "AND revision_root_id<>id AND revision_number>1 AND is_correction)",
    )
    op.create_check_constraint(
        "ck_experience_validity",
        "memory_experiences",
        "valid_from IS NULL OR expires_at IS NULL OR valid_from < expires_at",
    )
    op.create_check_constraint(
        "ck_experience_forgotten",
        "memory_experiences",
        "(status='forgotten' AND source_handoff_id IS NULL AND source='{}'::jsonb AND title='[forgotten]' "
        "AND content='[forgotten]' AND cardinality(tags)=0 AND search_text='') OR (status<>'forgotten' AND source_handoff_id IS NOT NULL)",
    )
    op.create_index(
        "uq_experience_active_family",
        "memory_experiences",
        [sa.text("coalesce(revision_root_id, id)")],
        unique=True,
        postgresql_where=sa.text("status='active'"),
    )
    op.create_index(
        "idx_experience_family",
        "memory_experiences",
        ["project_id", sa.text("coalesce(revision_root_id, id)"), "created_at", "id"],
    )
    op.add_column("memory_experience_events", sa.Column("related_memory_id", UUID()))
    op.drop_constraint("ck_experience_event_transition", "memory_experience_events", type_="check")
    op.create_check_constraint(
        "ck_experience_event_transition",
        "memory_experience_events",
        "(action='approve' AND previous_status='pending' AND applied_status='active') OR "
        "(action='reject' AND previous_status='pending' AND applied_status='rejected') OR "
        "(action='archive' AND previous_status='active' AND applied_status='archived') OR "
        "(action='supersede' AND previous_status='active' AND applied_status='superseded') OR "
        "(action='forget' AND previous_status IN ('pending','active','rejected','archived','superseded') AND applied_status='forgotten')",
    )
    op.create_table(
        "memory_experience_suppressions",
        sa.Column("project_id", sa.Text(), primary_key=True),
        sa.Column("source_payload_digest", sa.Text(), primary_key=True),
        sa.Column("content_fingerprint", sa.Text(), primary_key=True),
        sa.Column("memory_id", UUID(), sa.ForeignKey("memory_experiences.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("reason IN ('rejected','superseded','forgotten')", name="ck_experience_suppression_reason"),
        sa.CheckConstraint("version>=1", name="ck_experience_suppression_version"),
    )
    op.execute("""
        INSERT INTO memory_experience_suppressions
            (project_id, source_payload_digest, content_fingerprint, memory_id, reason, updated_by)
        SELECT e.project_id, e.source_payload_digest, e.content_fingerprint, e.id, 'rejected',
            coalesce((SELECT actor_id FROM memory_experience_events WHERE memory_id=e.id AND action='reject' LIMIT 1), e.created_by)
        FROM memory_experiences e WHERE e.status='rejected'
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        CREATE FUNCTION guard_experience_content() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF ROW(NEW.kind,NEW.source_lock_digest,NEW.source_payload_digest,NEW.content_fingerprint,
                   NEW.classification,NEW.supersedes_id,NEW.supersedes_version,NEW.revision_root_id,
                   NEW.revision_number,NEW.is_correction,NEW.submission_digest,NEW.idempotency_key,NEW.created_by,NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.kind,OLD.source_lock_digest,OLD.source_payload_digest,OLD.content_fingerprint,
                   OLD.classification,OLD.supersedes_id,OLD.supersedes_version,OLD.revision_root_id,
                   OLD.revision_number,OLD.is_correction,OLD.submission_digest,OLD.idempotency_key,OLD.created_by,OLD.created_at)
            THEN RAISE EXCEPTION 'Experience attribution and identity are immutable' USING ERRCODE='23514'; END IF;
            IF NEW.status<>'forgotten' OR OLD.status='forgotten' THEN
                IF ROW(NEW.title,NEW.content,NEW.tags,NEW.search_text,NEW.source,NEW.source_handoff_id)
                   IS DISTINCT FROM ROW(OLD.title,OLD.content,OLD.tags,OLD.search_text,OLD.source,OLD.source_handoff_id)
                THEN RAISE EXCEPTION 'Experience content is immutable' USING ERRCODE='23514'; END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER experience_content_immutable BEFORE UPDATE ON memory_experiences
        FOR EACH ROW EXECUTE FUNCTION guard_experience_content();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM memory_experiences WHERE supersedes_id IS NOT NULL OR status='forgotten' OR valid_from IS NOT NULL)"
            )
        )
        .scalar()
    ):
        raise RuntimeError(
            "Cannot downgrade M2 revision, forgotten or validity data to 004; use a forward fix or restore a backup"
        )
    op.execute(
        "DROP TRIGGER experience_content_immutable ON memory_experiences; DROP FUNCTION guard_experience_content()"
    )
    op.drop_table("memory_experience_suppressions")
    op.drop_constraint("ck_experience_event_transition", "memory_experience_events", type_="check")
    op.create_check_constraint(
        "ck_experience_event_transition",
        "memory_experience_events",
        "(action='approve' AND previous_status='pending' AND applied_status='active') OR "
        "(action='reject' AND previous_status='pending' AND applied_status='rejected') OR "
        "(action='archive' AND previous_status='active' AND applied_status='archived')",
    )
    op.drop_column("memory_experience_events", "related_memory_id")
    op.drop_index("idx_experience_family", table_name="memory_experiences")
    op.drop_index("uq_experience_active_family", table_name="memory_experiences")
    for name in ("ck_experience_forgotten", "ck_experience_validity", "ck_experience_revision"):
        op.drop_constraint(name, "memory_experiences", type_="check")
    op.drop_constraint("ck_experience_status", "memory_experiences", type_="check")
    op.create_check_constraint(
        "ck_experience_status", "memory_experiences", "status IN ('pending','active','rejected','archived')"
    )
    for column in ("supersedes_id", "revision_root_id"):
        op.drop_constraint("fk_experience_" + column, "memory_experiences", type_="foreignkey")
    op.drop_constraint("uq_experience_id_project", "memory_experiences", type_="unique")
    op.alter_column("memory_experiences", "source_handoff_id", nullable=False)
    for column in (
        "source_payload_digest",
        "content_fingerprint",
        "valid_from",
        "supersedes_id",
        "supersedes_version",
        "revision_root_id",
        "revision_number",
        "is_correction",
    ):
        op.drop_column("memory_experiences", column)
