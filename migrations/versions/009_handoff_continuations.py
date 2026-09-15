"""Addressed continuation packages, with legacy bytes and rollback protection.

Revision ID: 009
Revises: 008
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("handoffs", sa.Column("handoff_version", sa.SmallInteger(), nullable=False, server_default="1"))
    op.add_column("handoffs", sa.Column("recipient_user_id", sa.Text(), nullable=True))
    op.add_column("handoffs", sa.Column("continuation", JSONB(), nullable=True))
    op.add_column("handoffs", sa.Column("continuation_digest", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_handoffs_continuation", "handoffs",
        "(handoff_version=1 AND recipient_user_id IS NULL AND continuation IS NULL AND continuation_digest IS NULL) OR "
        "(handoff_version=2 AND (recipient_user_id IS NOT NULL OR continuation IS NOT NULL) AND "
        " ((continuation IS NULL AND continuation_digest IS NULL) OR "
        "  (continuation IS NOT NULL AND continuation_digest IS NOT NULL AND jsonb_typeof(continuation)='object' "
        "   AND continuation_digest ~ '^sha256:[0-9a-f]{64}$')))",
    )
    op.create_check_constraint("ck_handoffs_recipient", "handoffs",
                               "recipient_user_id IS NULL OR length(recipient_user_id) BETWEEN 1 AND 128")
    op.create_index("idx_handoffs_recipient", "handoffs", ["project_id", "recipient_user_id", "status", "created_at", "id"],
                    postgresql_where=sa.text("handoff_version=2"))


def downgrade():
    # Lock out concurrent writers before checking; never discard M8 history.
    op.execute("LOCK TABLE handoffs IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM handoffs WHERE handoff_version=2)")).scalar():
        raise RuntimeError("009 downgrade refused: addressed or continuation handoff history exists")
    op.drop_index("idx_handoffs_recipient", table_name="handoffs")
    op.drop_constraint("ck_handoffs_recipient", "handoffs", type_="check")
    op.drop_constraint("ck_handoffs_continuation", "handoffs", type_="check")
    for name in ("continuation_digest", "continuation", "recipient_user_id", "handoff_version"):
        op.drop_column("handoffs", name)
