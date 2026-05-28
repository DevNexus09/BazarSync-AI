"""add telegram snapshot logs

Revision ID: 7d2c3f6a9b0e
Revises: 4f3b6e8a92b1
Create Date: 2026-05-28 23:59:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7d2c3f6a9b0e"
down_revision: Union[str, Sequence[str], None] = "4f3b6e8a92b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "snapshot_logs" not in inspector.get_table_names():
        op.create_table(
            "snapshot_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("telegram_chat_id", sa.String(length=120), nullable=False),
            sa.Column(
                "sent_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        )
        op.create_index(
            "ix_snapshot_logs_seller_id", "snapshot_logs", ["seller_id"], unique=False
        )
        op.create_index(
            "ix_snapshot_logs_product_id", "snapshot_logs", ["product_id"], unique=False
        )
        op.create_index(
            "ix_snapshot_logs_status", "snapshot_logs", ["status"], unique=False
        )
        op.create_index(
            "ix_snapshot_logs_sent_at", "snapshot_logs", ["sent_at"], unique=False
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "snapshot_logs" in inspector.get_table_names():
        op.drop_index("ix_snapshot_logs_sent_at", table_name="snapshot_logs")
        op.drop_index("ix_snapshot_logs_status", table_name="snapshot_logs")
        op.drop_index("ix_snapshot_logs_product_id", table_name="snapshot_logs")
        op.drop_index("ix_snapshot_logs_seller_id", table_name="snapshot_logs")
        op.drop_table("snapshot_logs")
