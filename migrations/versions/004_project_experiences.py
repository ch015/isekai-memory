"""Source-backed project experiences and atomic review receipts.

Revision ID: 004
Revises: 003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_handoffs_id_project", "handoffs", ["id", "project_id"])
    op.create_table(
        "memory_experiences",
        sa.Column("id", UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("source_handoff_id", UUID(), nullable=False),
        sa.Column("source", JSONB(), nullable=False),
        sa.Column("source_lock_digest", sa.Text(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", ARRAY(sa.Text()), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column(
            "search_document", TSVECTOR(),
            sa.Computed("to_tsvector('simple'::regconfig, search_text)", persisted=True),
        ),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("submission_digest", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_handoff_id", "project_id"], ["handoffs.id", "handoffs.project_id"],
            name="fk_experience_source_project", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("project_id", "created_by", "idempotency_key", name="uq_experience_submission"),
        sa.CheckConstraint("kind IN ('fact','decision','constraint','lesson','procedure')", name="ck_experience_kind"),
        sa.CheckConstraint("status IN ('pending','active','rejected','archived')", name="ck_experience_status"),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')", name="ck_experience_classification",
        ),
        sa.CheckConstraint("version >= 1", name="ck_experience_version"),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 200", name="ck_experience_title"),
        sa.CheckConstraint("char_length(content) BETWEEN 1 AND 4096", name="ck_experience_content"),
        sa.CheckConstraint("cardinality(tags) <= 16", name="ck_experience_tags"),
    )
    op.create_index("idx_experiences_project_status", "memory_experiences", ["project_id", "status", "created_at", "id"])
    op.create_index("idx_experiences_source", "memory_experiences", ["source_handoff_id", "project_id"])
    op.create_index(
        "idx_experiences_search", "memory_experiences", ["search_document"],
        postgresql_using="gin", postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "memory_experience_events",
        sa.Column("memory_id", UUID(), sa.ForeignKey("memory_experiences.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("previous_status", sa.Text(), nullable=False),
        sa.Column("applied_status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("version >= 2", name="ck_experience_event_version"),
        sa.CheckConstraint(
            "(action='approve' AND previous_status='pending' AND applied_status='active') OR "
            "(action='reject' AND previous_status='pending' AND applied_status='rejected') OR "
            "(action='archive' AND previous_status='active' AND applied_status='archived')",
            name="ck_experience_event_transition",
        ),
    )


def downgrade() -> None:
    op.drop_table("memory_experience_events")
    op.drop_table("memory_experiences")
    op.drop_constraint("uq_handoffs_id_project", "handoffs", type_="unique")
