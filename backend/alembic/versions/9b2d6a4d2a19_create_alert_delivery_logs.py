"""create alert delivery logs

Revision ID: 9b2d6a4d2a19
Revises: c6e6f2b1b19a
Create Date: 2026-05-28 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9b2d6a4d2a19"
down_revision: Union[str, Sequence[str], None] = "c6e6f2b1b19a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "alerts" not in tables or "alert_delivery_logs" in tables:
        return

    op.create_table(
        "alert_delivery_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_chat_id", sa.String(length=120), nullable=True),
        sa.Column(
            "delivery_status",
            postgresql.ENUM(
                "delivered",
                "failed",
                "pending",
                "duplicate",
                name="alert_delivery_status",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_alert_delivery_logs_seller_id",
        "alert_delivery_logs",
        ["seller_id"],
        unique=False,
    )
    op.create_index(
        "ix_alert_delivery_logs_alert_id",
        "alert_delivery_logs",
        ["alert_id"],
        unique=False,
    )
    op.create_index(
        "ix_alert_delivery_logs_status",
        "alert_delivery_logs",
        ["delivery_status"],
        unique=False,
    )
    op.create_index(
        "ix_alert_delivery_logs_sent_at",
        "alert_delivery_logs",
        ["sent_at"],
        unique=False,
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "alert_delivery_logs" not in inspector.get_table_names():
        return
    op.drop_index("ix_alert_delivery_logs_sent_at", table_name="alert_delivery_logs")
    op.drop_index("ix_alert_delivery_logs_status", table_name="alert_delivery_logs")
    op.drop_index("ix_alert_delivery_logs_alert_id", table_name="alert_delivery_logs")
    op.drop_index("ix_alert_delivery_logs_seller_id", table_name="alert_delivery_logs")
    op.drop_table("alert_delivery_logs")
