"""add copilot message feedback

Revision ID: n8b9c0d1e2f3
Revises: m7a8b9c0d1e2
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "n8b9c0d1e2f3"
down_revision: str | None = "m7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Additive: a new table only; no existing rows or columns change.
    op.create_table(
        "copilot_message_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", sa.String(length=8), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["copilot_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["copilot_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "message_id", name="uq_copilot_message_feedback_seller_message"),
        sa.CheckConstraint("rating IN ('UP', 'DOWN')", name="ck_copilot_message_feedback_rating"),
    )
    op.create_index("ix_copilot_message_feedback_seller_created", "copilot_message_feedback", ["seller_id", "created_at"])
    op.create_index("ix_copilot_message_feedback_rating", "copilot_message_feedback", ["rating"])


def downgrade() -> None:
    op.drop_index("ix_copilot_message_feedback_rating", table_name="copilot_message_feedback")
    op.drop_index("ix_copilot_message_feedback_seller_created", table_name="copilot_message_feedback")
    op.drop_table("copilot_message_feedback")
