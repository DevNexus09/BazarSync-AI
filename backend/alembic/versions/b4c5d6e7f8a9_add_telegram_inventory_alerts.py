"""add telegram inventory alerts

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-06-29 00:00:09.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ALERT_TYPES = (
    "CRITICAL_RISK",
    "HIGH_RISK",
    "RISK_ESCALATION",
    "REORDER_DEADLINE",
    "DAYS_REMAINING_DROP",
    "OUT_OF_STOCK",
)
ALERT_STATUSES = ("PENDING", "SENDING", "SENT", "FAILED", "CANCELLED")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "telegram_inventory_alert_type" not in enum_names:
        postgresql.ENUM(*ALERT_TYPES, name="telegram_inventory_alert_type").create(bind, checkfirst=True)
    if "telegram_inventory_alert_status" not in enum_names:
        postgresql.ENUM(*ALERT_STATUSES, name="telegram_inventory_alert_status").create(bind, checkfirst=True)

    if "telegram_inventory_alerts" not in set(inspector.get_table_names()):
        op.create_table(
            "telegram_inventory_alerts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("risk_assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("reorder_recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("alert_type", postgresql.ENUM(*ALERT_TYPES, name="telegram_inventory_alert_type", create_type=False), nullable=False),
            sa.Column("dedupe_key", sa.String(length=255), nullable=False),
            sa.Column("status", postgresql.ENUM(*ALERT_STATUSES, name="telegram_inventory_alert_status", create_type=False), nullable=False),
            sa.Column("message_text", sa.Text(), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failure_code", sa.String(length=80), nullable=True),
            sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["risk_assessment_id"], ["inventory_risk_assessments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["reorder_recommendation_id"], ["reorder_recommendations.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("dedupe_key", name="uq_telegram_inventory_alerts_dedupe_key"),
        )
        op.create_index("ix_telegram_inventory_alerts_seller_status", "telegram_inventory_alerts", ["seller_id", "status"])
        op.create_index("ix_telegram_inventory_alerts_product_created", "telegram_inventory_alerts", ["product_id", "created_at"])
        op.create_index("ix_telegram_inventory_alerts_next_attempt", "telegram_inventory_alerts", ["status", "next_attempt_at"])
        op.create_index("ix_telegram_inventory_alerts_risk", "telegram_inventory_alerts", ["risk_assessment_id"])
        op.create_index("ix_telegram_inventory_alerts_reorder", "telegram_inventory_alerts", ["reorder_recommendation_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "telegram_inventory_alerts" in set(inspector.get_table_names()):
        op.drop_index("ix_telegram_inventory_alerts_reorder", table_name="telegram_inventory_alerts")
        op.drop_index("ix_telegram_inventory_alerts_risk", table_name="telegram_inventory_alerts")
        op.drop_index("ix_telegram_inventory_alerts_next_attempt", table_name="telegram_inventory_alerts")
        op.drop_index("ix_telegram_inventory_alerts_product_created", table_name="telegram_inventory_alerts")
        op.drop_index("ix_telegram_inventory_alerts_seller_status", table_name="telegram_inventory_alerts")
        op.drop_table("telegram_inventory_alerts")
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "telegram_inventory_alert_status" in enum_names:
        postgresql.ENUM(name="telegram_inventory_alert_status").drop(bind, checkfirst=True)
    if "telegram_inventory_alert_type" in enum_names:
        postgresql.ENUM(name="telegram_inventory_alert_type").drop(bind, checkfirst=True)
