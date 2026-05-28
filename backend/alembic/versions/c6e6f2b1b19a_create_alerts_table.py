"""create alerts table

Revision ID: c6e6f2b1b19a
Revises: 4f3b6e8a92b1
Create Date: 2026-05-28 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c6e6f2b1b19a"
down_revision: Union[str, Sequence[str], None] = "4f3b6e8a92b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}

    _ensure_enum(
        enum_names,
        "alert_urgency_level",
        ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    )
    _ensure_enum(
        enum_names,
        "alert_action_type",
        [
            "PRICE_LOWER",
            "PRICE_RAISE",
            "HOLD",
            "REORDER",
            "STOCK_WARNING",
            "OPPORTUNITY_CAPTURE",
        ],
    )
    _ensure_enum(enum_names, "alert_confidence", ["LOW", "MEDIUM", "HIGH"])
    _ensure_enum(
        enum_names,
        "alert_delivery_status",
        ["delivered", "failed", "pending", "duplicate"],
    )

    existing_tables = set(inspector.get_table_names())
    if "alerts" not in existing_tables:
        op.create_table(
            "alerts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "alert_type",
                sa.String(length=120),
                nullable=False,
                server_default=sa.text("'urgency_alert'"),
            ),
            sa.Column(
                "urgency_level",
                postgresql.ENUM(
                    "LOW",
                    "MEDIUM",
                    "HIGH",
                    "CRITICAL",
                    name="alert_urgency_level",
                    create_type=False,
                ),
                nullable=False,
                server_default=sa.text("'MEDIUM'"),
            ),
            sa.Column(
                "action_type",
                postgresql.ENUM(
                    "PRICE_LOWER",
                    "PRICE_RAISE",
                    "HOLD",
                    "REORDER",
                    "STOCK_WARNING",
                    "OPPORTUNITY_CAPTURE",
                    name="alert_action_type",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column(
                "confidence",
                postgresql.ENUM(
                    "LOW",
                    "MEDIUM",
                    "HIGH",
                    name="alert_confidence",
                    create_type=False,
                ),
                nullable=False,
            ),
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
            sa.Column("telegram_message_id", sa.String(length=120), nullable=True),
            sa.Column("telegram_chat_id", sa.String(length=120), nullable=True),
            sa.Column("delivery_error", sa.Text(), nullable=True),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["recommendation_id"],
                ["recommendations.id"],
                ondelete="SET NULL",
            ),
        )
        existing_indexes: set[str] = set()
    else:
        existing_indexes = {index["name"] for index in inspector.get_indexes("alerts")}

    if "ix_alerts_seller_id" not in existing_indexes:
        op.create_index("ix_alerts_seller_id", "alerts", ["seller_id"], unique=False)
    if "ix_alerts_product_id" not in existing_indexes:
        op.create_index("ix_alerts_product_id", "alerts", ["product_id"], unique=False)
    if "ix_alerts_recommendation_id" not in existing_indexes:
        op.create_index(
            "ix_alerts_recommendation_id", "alerts", ["recommendation_id"], unique=False
        )
    if "ix_alerts_delivery_status" not in existing_indexes:
        op.create_index(
            "ix_alerts_delivery_status", "alerts", ["delivery_status"], unique=False
        )
    if "ix_alerts_urgency_level" not in existing_indexes:
        op.create_index("ix_alerts_urgency_level", "alerts", ["urgency_level"], unique=False)
    if "ix_alerts_created_at" not in existing_indexes:
        op.create_index("ix_alerts_created_at", "alerts", ["created_at"], unique=False)

    existing_tables = set(inspector.get_table_names())
    if "alerts" in existing_tables and "alert_delivery_logs" not in existing_tables:
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
        existing_tables.add("alert_delivery_logs")
        log_indexes: set[str] = set()
    else:
        log_indexes = {
            index["name"] for index in inspector.get_indexes("alert_delivery_logs")
        } if "alert_delivery_logs" in existing_tables else set()

    if "alert_delivery_logs" in existing_tables:
        if "ix_alert_delivery_logs_seller_id" not in log_indexes:
            op.create_index(
                "ix_alert_delivery_logs_seller_id",
                "alert_delivery_logs",
                ["seller_id"],
                unique=False,
            )
        if "ix_alert_delivery_logs_alert_id" not in log_indexes:
            op.create_index(
                "ix_alert_delivery_logs_alert_id",
                "alert_delivery_logs",
                ["alert_id"],
                unique=False,
            )
        if "ix_alert_delivery_logs_status" not in log_indexes:
            op.create_index(
                "ix_alert_delivery_logs_status",
                "alert_delivery_logs",
                ["delivery_status"],
                unique=False,
            )
        if "ix_alert_delivery_logs_sent_at" not in log_indexes:
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

    if "alerts" in inspector.get_table_names():
        op.drop_index("ix_alerts_created_at", table_name="alerts")
        op.drop_index("ix_alerts_urgency_level", table_name="alerts")
        op.drop_index("ix_alerts_delivery_status", table_name="alerts")
        op.drop_index("ix_alerts_recommendation_id", table_name="alerts")
        op.drop_index("ix_alerts_product_id", table_name="alerts")
        op.drop_index("ix_alerts_seller_id", table_name="alerts")
        op.drop_table("alerts")


def _ensure_enum(enum_names: set[str], name: str, values: list[str]) -> None:
    if name in enum_names:
        return
    values_sql = ", ".join(f"'{value}'" for value in values)
    op.execute(sa.text(f"CREATE TYPE {name} AS ENUM ({values_sql})"))
    enum_names.add(name)
