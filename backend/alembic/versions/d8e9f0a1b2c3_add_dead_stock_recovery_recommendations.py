"""add dead stock recovery recommendations

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-07-03 00:00:02.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ACTION_VALUES = ("BUNDLE", "DISCOUNT", "FLASH_SALE", "SEO_FIX", "HOLD", "MANUAL_REVIEW")
STATUS_VALUES = ("OPEN", "ACKNOWLEDGED", "DISMISSED", "EXPIRED", "SUPERSEDED", "INSUFFICIENT_DATA")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "dead_stock_recovery_action" not in enum_names:
        postgresql.ENUM(*ACTION_VALUES, name="dead_stock_recovery_action").create(bind, checkfirst=True)
    if "dead_stock_recovery_status" not in enum_names:
        postgresql.ENUM(*STATUS_VALUES, name="dead_stock_recovery_status").create(bind, checkfirst=True)

    if "dead_stock_recovery_recommendations" not in set(inspector.get_table_names()):
        op.create_table(
            "dead_stock_recovery_recommendations",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("dead_stock_assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("primary_action", postgresql.ENUM(*ACTION_VALUES, name="dead_stock_recovery_action", create_type=False), nullable=False),
            sa.Column("secondary_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("recommended_discount_rate", sa.Numeric(precision=7, scale=6), nullable=True),
            sa.Column("recommended_price", sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column("suggested_duration_days", sa.Integer(), nullable=True),
            sa.Column("recommended_quantity", sa.Integer(), nullable=True),
            sa.Column("confidence_score", sa.Numeric(precision=5, scale=2), nullable=False),
            sa.Column("recommendation_status", postgresql.ENUM(*STATUS_VALUES, name="dead_stock_recovery_status", create_type=False), nullable=False),
            sa.Column("explanation", sa.String(length=1000), nullable=False),
            sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("rejected_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("calculation_version", sa.String(length=20), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["dead_stock_assessment_id"], ["dead_stock_assessments.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("dead_stock_assessment_id", "calculation_version", name="uq_dead_stock_recovery_assessment_version"),
            sa.CheckConstraint("recommended_discount_rate IS NULL OR (recommended_discount_rate >= 0 AND recommended_discount_rate < 1)", name="ck_dead_stock_recovery_discount_rate"),
            sa.CheckConstraint("recommended_price IS NULL OR recommended_price >= 0", name="ck_dead_stock_recovery_price"),
            sa.CheckConstraint("suggested_duration_days IS NULL OR suggested_duration_days > 0", name="ck_dead_stock_recovery_duration"),
            sa.CheckConstraint("recommended_quantity IS NULL OR recommended_quantity >= 0", name="ck_dead_stock_recovery_quantity"),
            sa.CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_dead_stock_recovery_confidence"),
        )
        op.create_index("ix_dead_stock_recovery_seller_status", "dead_stock_recovery_recommendations", ["seller_id", "recommendation_status"])
        op.create_index("ix_dead_stock_recovery_product_generated", "dead_stock_recovery_recommendations", ["product_id", "generated_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dead_stock_recovery_recommendations" in set(inspector.get_table_names()):
        op.drop_index("ix_dead_stock_recovery_product_generated", table_name="dead_stock_recovery_recommendations")
        op.drop_index("ix_dead_stock_recovery_seller_status", table_name="dead_stock_recovery_recommendations")
        op.drop_table("dead_stock_recovery_recommendations")

    enum_names = {enum["name"] for enum in inspector.get_enums()}
    for enum_name in ("dead_stock_recovery_status", "dead_stock_recovery_action"):
        if enum_name in enum_names:
            postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
