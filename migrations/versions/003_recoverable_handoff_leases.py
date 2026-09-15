"""Add recoverable, token-bound handoff leases.

Revision ID: 003
Revises: 002
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "handoffs",
        sa.Column("classification", sa.Text(), server_default=sa.text("'internal'"), nullable=False),
    )
    op.add_column("handoffs", sa.Column("claim_token_digest", sa.Text(), nullable=True))
    op.add_column("handoffs", sa.Column("claim_lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "handoffs",
        sa.Column("claim_generation", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("handoffs", sa.Column("claim_disposition", sa.Text(), nullable=True))
    op.add_column("handoffs", sa.Column("claim_reason_code", sa.Text(), nullable=True))

    op.drop_constraint("ck_handoffs_status", "handoffs", type_="check")
    op.create_check_constraint(
        "ck_handoffs_status",
        "handoffs",
        "status IN ('pending', 'claimed', 'acknowledged', 'expired')",
    )
    op.create_check_constraint(
        "ck_handoffs_classification",
        "handoffs",
        "classification IN ('public', 'internal', 'confidential', 'restricted')",
    )
    op.create_check_constraint(
        "ck_handoffs_claim_disposition",
        "handoffs",
        "claim_disposition IS NULL OR claim_disposition IN ('acknowledged', 'nacked')",
    )
    op.create_check_constraint(
        "ck_handoffs_claim_reason",
        "handoffs",
        "claim_reason_code IS NULL OR claim_reason_code IN "
        "('retryable', 'processing_failed', 'shutdown', 'cancelled')",
    )
    op.create_index(
        "idx_handoffs_recoverable_claims",
        "handoffs",
        ["project_id", "status", "claim_lease_expires_at"],
        postgresql_where=sa.text("status IN ('pending', 'claimed')"),
    )
    op.create_index(
        "idx_handoffs_claim_owner",
        "handoffs",
        ["project_id", "claimed_by", "status"],
        postgresql_where=sa.text("claim_token_digest IS NOT NULL"),
    )
    op.create_table(
        "handoff_claim_receipts",
        sa.Column("id", UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "handoff_id",
            UUID(),
            sa.ForeignKey("handoffs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("claim_token_digest", sa.Text(), nullable=False),
        sa.Column("claim_generation", sa.BigInteger(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "handoff_id",
            "project_id",
            "actor_id",
            "claim_token_digest",
            "operation",
            name="uq_handoff_claim_receipt",
        ),
        sa.CheckConstraint("operation IN ('acknowledged', 'nacked')", name="ck_handoff_receipt_operation"),
        sa.CheckConstraint(
            "reason_code IS NULL OR reason_code IN ('retryable', 'processing_failed', 'shutdown', 'cancelled')",
            name="ck_handoff_receipt_reason",
        ),
    )
    op.create_index(
        "idx_handoff_claim_receipts_guard",
        "handoff_claim_receipts",
        ["handoff_id", "project_id", "actor_id", "claim_token_digest"],
    )


def downgrade() -> None:
    op.drop_table("handoff_claim_receipts")
    op.drop_index("idx_handoffs_claim_owner", table_name="handoffs")
    op.drop_index("idx_handoffs_recoverable_claims", table_name="handoffs")
    op.drop_constraint("ck_handoffs_claim_reason", "handoffs", type_="check")
    op.drop_constraint("ck_handoffs_claim_disposition", "handoffs", type_="check")
    op.drop_constraint("ck_handoffs_classification", "handoffs", type_="check")
    op.drop_constraint("ck_handoffs_status", "handoffs", type_="check")
    # An acknowledged row cannot be represented by revision 002. Keep it consumed.
    op.execute("UPDATE handoffs SET status = 'claimed' WHERE status = 'acknowledged'")
    op.create_check_constraint(
        "ck_handoffs_status",
        "handoffs",
        "status IN ('pending', 'claimed', 'expired')",
    )
    op.drop_column("handoffs", "claim_reason_code")
    op.drop_column("handoffs", "claim_disposition")
    op.drop_column("handoffs", "claim_generation")
    op.drop_column("handoffs", "claim_lease_expires_at")
    op.drop_column("handoffs", "claim_token_digest")
    op.drop_column("handoffs", "classification")
