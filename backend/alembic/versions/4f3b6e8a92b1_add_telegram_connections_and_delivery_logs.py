"""add telegram connections and delivery logs

Revision ID: 4f3b6e8a92b1
Revises: 1c8c3e4d9a5b
Create Date: 2026-05-28 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4f3b6e8a92b1"
down_revision: Union[str, Sequence[str], None] = "1c8c3e4d9a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "seller_telegram_connections" not in inspector.get_table_names():
        op.create_table(
            "seller_telegram_connections",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
            sa.Column("telegram_chat_id", sa.String(length=120), nullable=True),
            sa.Column("telegram_username", sa.String(length=120), nullable=True),
            sa.Column("telegram_first_name", sa.String(length=120), nullable=True),
            sa.Column("telegram_last_name", sa.String(length=120), nullable=True),
            sa.Column("connection_token", sa.String(length=128), nullable=True),
            sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "is_connected",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_alert_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        )
        existing_indexes: set[str] = set()
    else:
        existing_indexes = {
            index["name"]
            for index in inspector.get_indexes("seller_telegram_connections")
        }

    if "ix_seller_telegram_connections_seller_id" not in existing_indexes:
        op.create_index(
            "ix_seller_telegram_connections_seller_id",
            "seller_telegram_connections",
            ["seller_id"],
            unique=True,
        )
    if "ix_seller_telegram_connections_token" not in existing_indexes:
        op.create_index(
            "ix_seller_telegram_connections_token",
            "seller_telegram_connections",
            ["connection_token"],
            unique=False,
        )
    if "ix_seller_telegram_connections_chat_id" not in existing_indexes:
        op.create_index(
            "ix_seller_telegram_connections_chat_id",
            "seller_telegram_connections",
            ["telegram_chat_id"],
            unique=False,
        )
    if "ix_seller_telegram_connections_is_connected" not in existing_indexes:
        op.create_index(
            "ix_seller_telegram_connections_is_connected",
            "seller_telegram_connections",
            ["is_connected"],
            unique=False,
        )
    if "alerts" in inspector.get_table_names():
        op.create_table(
            "alert_delivery_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("telegram_chat_id", sa.String(length=120), nullable=True),
            sa.Column(
                "delivery_status",
                sa.Enum(
                    "delivered",
                    "failed",
                    "pending",
                    "duplicate",
                    name="alert_delivery_status",
                ),
                nullable=False,
                server_default="pending",
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
    if "alert_delivery_logs" in inspector.get_table_names():
        op.drop_index("ix_alert_delivery_logs_sent_at", table_name="alert_delivery_logs")
        op.drop_index("ix_alert_delivery_logs_status", table_name="alert_delivery_logs")
        op.drop_index("ix_alert_delivery_logs_alert_id", table_name="alert_delivery_logs")
        op.drop_index("ix_alert_delivery_logs_seller_id", table_name="alert_delivery_logs")
        op.drop_table("alert_delivery_logs")

    if "seller_telegram_connections" in inspector.get_table_names():
        op.drop_index(
            "ix_seller_telegram_connections_is_connected",
            table_name="seller_telegram_connections",
        )
        op.drop_index(
            "ix_seller_telegram_connections_chat_id",
            table_name="seller_telegram_connections",
        )
        op.drop_index(
            "ix_seller_telegram_connections_token",
            table_name="seller_telegram_connections",
        )
        op.drop_index(
            "ix_seller_telegram_connections_seller_id",
            table_name="seller_telegram_connections",
        )
        op.drop_table("seller_telegram_connections")
