"""Initial schema — artifacts, artifact_policies, handoffs, access_tokens.

Revision ID: 001
Revises: None
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, JSONB, UUID

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Artifact Registry ---
    op.create_table(
        "artifacts",
        sa.Column("id", UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("manifest_digest", sa.Text(), nullable=False),
        sa.Column("artifact_digest", sa.Text(), nullable=False),
        sa.Column("archive_blob", BYTEA(), nullable=True),
        sa.Column("archive_url", sa.Text(), nullable=True),
        sa.Column("published_by", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("metadata", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.UniqueConstraint("artifact_id", "kind", "version", name="uq_artifact_identity"),
    )
    op.create_index("idx_artifacts_kind_id", "artifacts", ["kind", "artifact_id"])

    # --- Artifact Policies ---
    op.create_table(
        "artifact_policies",
        sa.Column("id", UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("organization_id", sa.Text(), nullable=False),
        sa.Column("project_pattern", sa.Text(), server_default="*", nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("version_range", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_policies_org", "artifact_policies", ["organization_id"])

    # --- Work Handoff ---
    op.create_table(
        "handoffs",
        sa.Column("id", UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("unit_id", sa.Text(), nullable=False),
        sa.Column("phase_attempt_id", sa.Text(), nullable=False),
        sa.Column("phase_id", sa.Text(), nullable=False),
        sa.Column("from_user", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("claimed_by", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        # Summary fields
        sa.Column("task_summary", sa.Text(), nullable=True),
        sa.Column("result_status", sa.Text(), nullable=False),
        sa.Column("passed_checks", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=True),
        sa.Column("artifacts_produced", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=True),
        sa.Column("handoff_note", sa.Text(), nullable=True),
        # Full envelopes
        sa.Column("task_envelope", JSONB(), nullable=False),
        sa.Column("result_envelope", JSONB(), nullable=False),
        sa.Column("context_digest", sa.Text(), nullable=False),
        sa.Column("raw_output", sa.Text(), nullable=True),
        # Integrity
        sa.Column("lock_snapshot_digest", sa.Text(), nullable=False),
        sa.Column("envelope_digest", sa.Text(), nullable=False),
        sa.UniqueConstraint("project_id", "phase_attempt_id", name="uq_handoff_phase_attempt"),
    )
    op.create_index(
        "idx_handoffs_project_status",
        "handoffs",
        ["project_id", "status"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("idx_handoffs_unit", "handoffs", ["project_id", "unit_id", sa.text("created_at DESC")])

    # --- Access Tokens ---
    op.create_table(
        "access_tokens",
        sa.Column("id", UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("scopes", ARRAY(sa.Text()), server_default=sa.text("'{read,write}'"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_tokens_hash", "access_tokens", ["token_hash"])


def downgrade() -> None:
    op.drop_table("access_tokens")
    op.drop_table("handoffs")
    op.drop_table("artifact_policies")
    op.drop_table("artifacts")
