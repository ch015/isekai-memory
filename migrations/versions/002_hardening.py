"""Harden integrity, policy identity, and token lifecycle.

Revision ID: 002
Revises: 001
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("artifacts", sa.Column("archive_digest", sa.Text(), nullable=True))
    # In revision 001 artifact_digest contained the archive byte digest. Preserve
    # that value as archive_digest so existing rows remain readable; republishing
    # is required to establish the logical Core artifact digest.
    op.execute("UPDATE artifacts SET archive_digest = artifact_digest WHERE archive_digest IS NULL")
    op.alter_column("artifacts", "archive_digest", nullable=False)

    op.add_column("access_tokens", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("handoffs", sa.Column("payload_digest", sa.Text(), nullable=True))
    op.execute("UPDATE handoffs SET payload_digest = envelope_digest WHERE payload_digest IS NULL")
    op.alter_column("handoffs", "payload_digest", nullable=False)

    # Collapse accidental duplicate policy keys before making upsert deterministic.
    op.execute(
        """
        DELETE FROM artifact_policies older
        USING artifact_policies newer
        WHERE older.organization_id = newer.organization_id
          AND older.project_pattern = newer.project_pattern
          AND older.kind = newer.kind
          AND older.artifact_id = newer.artifact_id
          AND (older.updated_at, older.id) < (newer.updated_at, newer.id)
        """
    )
    op.create_unique_constraint(
        "uq_policy_identity",
        "artifact_policies",
        ["organization_id", "project_pattern", "kind", "artifact_id"],
    )

    op.create_check_constraint("ck_artifacts_kind", "artifacts", "kind IN ('foundation', 'preset')")
    op.create_check_constraint(
        "ck_artifacts_storage",
        "artifacts",
        "(archive_blob IS NOT NULL AND archive_url IS NULL) OR (archive_blob IS NULL AND archive_url IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_handoffs_status",
        "handoffs",
        "status IN ('pending', 'claimed', 'expired')",
    )
    op.create_check_constraint(
        "ck_handoffs_result_status",
        "handoffs",
        "result_status IN ('succeeded', 'failed', 'cancelled', 'lost')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_handoffs_result_status", "handoffs", type_="check")
    op.drop_constraint("ck_handoffs_status", "handoffs", type_="check")
    op.drop_constraint("ck_artifacts_storage", "artifacts", type_="check")
    op.drop_constraint("ck_artifacts_kind", "artifacts", type_="check")
    op.drop_constraint("uq_policy_identity", "artifact_policies", type_="unique")
    op.drop_column("handoffs", "payload_digest")
    op.drop_column("access_tokens", "revoked_at")
    op.drop_column("artifacts", "archive_digest")
