"""add pricing policy fee foundation

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-01 09:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


pricing_objective = postgresql.ENUM(
    "MAXIMIZE_EXPECTED_PROFIT",
    "MAXIMIZE_REVENUE_WITH_MARGIN_FLOOR",
    "PROTECT_INVENTORY",
    "CLEAR_EXCESS_STOCK",
    name="pricing_objective",
    create_type=False,
)


def upgrade() -> None:
    pricing_objective.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "pricing_policies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("seller_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("marketplace", sa.String(length=120), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("minimum_margin_rate", sa.Numeric(7, 6), nullable=False),
        sa.Column("minimum_unit_profit", sa.Numeric(12, 2), nullable=False),
        sa.Column("maximum_price_decrease_rate", sa.Numeric(7, 6), nullable=True),
        sa.Column("maximum_price_increase_rate", sa.Numeric(7, 6), nullable=True),
        sa.Column("minimum_allowed_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("maximum_allowed_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_increment", sa.Numeric(12, 2), nullable=False),
        sa.Column("recommendation_cooldown_hours", sa.Integer(), nullable=False),
        sa.Column("objective", pricing_objective, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="ck_pricing_policies_effective_period"),
        sa.CheckConstraint("maximum_allowed_price IS NULL OR maximum_allowed_price >= 0", name="ck_pricing_policies_max_price"),
        sa.CheckConstraint("maximum_price_decrease_rate IS NULL OR (maximum_price_decrease_rate >= 0 AND maximum_price_decrease_rate < 1)", name="ck_pricing_policies_max_decrease_rate"),
        sa.CheckConstraint("maximum_price_increase_rate IS NULL OR maximum_price_increase_rate >= 0", name="ck_pricing_policies_max_increase_rate"),
        sa.CheckConstraint("minimum_allowed_price IS NULL OR minimum_allowed_price >= 0", name="ck_pricing_policies_min_price"),
        sa.CheckConstraint("minimum_allowed_price IS NULL OR maximum_allowed_price IS NULL OR minimum_allowed_price <= maximum_allowed_price", name="ck_pricing_policies_price_bounds"),
        sa.CheckConstraint("minimum_margin_rate >= 0 AND minimum_margin_rate < 1", name="ck_pricing_policies_min_margin_rate"),
        sa.CheckConstraint("minimum_unit_profit >= 0", name="ck_pricing_policies_min_unit_profit"),
        sa.CheckConstraint("price_increment > 0", name="ck_pricing_policies_price_increment"),
        sa.CheckConstraint("recommendation_cooldown_hours >= 0", name="ck_pricing_policies_cooldown"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "product_id", "marketplace", "effective_from", name="uq_pricing_policies_scope_start"),
    )
    op.create_index("ix_pricing_policies_effective", "pricing_policies", ["effective_from", "effective_to"])
    op.create_index("ix_pricing_policies_product_marketplace_active", "pricing_policies", ["product_id", "marketplace", "is_active"])
    op.create_index("ix_pricing_policies_seller_marketplace_active", "pricing_policies", ["seller_id", "marketplace", "is_active"])
    op.create_index(
        "uq_pricing_policies_active_product_marketplace",
        "pricing_policies",
        ["seller_id", "product_id", "marketplace"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "marketplace_fee_policies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("seller_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("marketplace", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("percentage_commission_rate", sa.Numeric(7, 6), nullable=False),
        sa.Column("payment_fee_rate", sa.Numeric(7, 6), nullable=False),
        sa.Column("fixed_per_order_fee", sa.Numeric(12, 2), nullable=False),
        sa.Column("fixed_per_unit_fee", sa.Numeric(12, 2), nullable=False),
        sa.Column("fulfilment_fee", sa.Numeric(12, 2), nullable=False),
        sa.Column("shipping_subsidy", sa.Numeric(12, 2), nullable=False),
        sa.Column("other_variable_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="ck_marketplace_fee_effective_period"),
        sa.CheckConstraint("fixed_per_order_fee >= 0", name="ck_marketplace_fee_fixed_order"),
        sa.CheckConstraint("fixed_per_unit_fee >= 0", name="ck_marketplace_fee_fixed_unit"),
        sa.CheckConstraint("fulfilment_fee >= 0", name="ck_marketplace_fee_fulfilment"),
        sa.CheckConstraint("other_variable_cost >= 0", name="ck_marketplace_fee_other_variable"),
        sa.CheckConstraint("payment_fee_rate >= 0 AND payment_fee_rate < 1", name="ck_marketplace_fee_payment_rate"),
        sa.CheckConstraint("percentage_commission_rate + payment_fee_rate < 1", name="ck_marketplace_fee_total_rate"),
        sa.CheckConstraint("percentage_commission_rate >= 0 AND percentage_commission_rate < 1", name="ck_marketplace_fee_commission_rate"),
        sa.CheckConstraint("shipping_subsidy >= 0", name="ck_marketplace_fee_shipping_subsidy"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "marketplace", "product_id", "category", "version", name="uq_marketplace_fee_policy_version"),
    )
    op.create_index("ix_marketplace_fee_category_active", "marketplace_fee_policies", ["seller_id", "marketplace", "category", "is_active"])
    op.create_index("ix_marketplace_fee_effective", "marketplace_fee_policies", ["effective_from", "effective_to"])
    op.create_index("ix_marketplace_fee_product_active", "marketplace_fee_policies", ["product_id", "is_active"])
    op.create_index("ix_marketplace_fee_seller_marketplace_active", "marketplace_fee_policies", ["seller_id", "marketplace", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_marketplace_fee_seller_marketplace_active", table_name="marketplace_fee_policies")
    op.drop_index("ix_marketplace_fee_product_active", table_name="marketplace_fee_policies")
    op.drop_index("ix_marketplace_fee_effective", table_name="marketplace_fee_policies")
    op.drop_index("ix_marketplace_fee_category_active", table_name="marketplace_fee_policies")
    op.drop_table("marketplace_fee_policies")

    op.drop_index("uq_pricing_policies_active_product_marketplace", table_name="pricing_policies")
    op.drop_index("ix_pricing_policies_seller_marketplace_active", table_name="pricing_policies")
    op.drop_index("ix_pricing_policies_product_marketplace_active", table_name="pricing_policies")
    op.drop_index("ix_pricing_policies_effective", table_name="pricing_policies")
    op.drop_table("pricing_policies")
    pricing_objective.drop(op.get_bind(), checkfirst=True)
