"""add pricing analytics snapshots

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-07-01 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


pricing_analytics_data_status = postgresql.ENUM(
    "SUFFICIENT",
    "LIMITED",
    "INSUFFICIENT",
    "STALE",
    name="pricing_analytics_data_status",
    create_type=False,
)


def upgrade() -> None:
    pricing_analytics_data_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "pricing_analytics_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("seller_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("competitor_scrape_run_id", sa.UUID(), nullable=True),
        sa.Column("inventory_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("sales_velocity_id", sa.UUID(), nullable=True),
        sa.Column("fee_policy_id", sa.UUID(), nullable=True),
        sa.Column("current_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("percentage_fee_rate", sa.Numeric(7, 6), nullable=False),
        sa.Column("fixed_fee_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("current_unit_profit", sa.Numeric(12, 2), nullable=False),
        sa.Column("current_margin_rate", sa.Numeric(8, 6), nullable=True),
        sa.Column("minimum_safe_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("competitor_min_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("competitor_q1_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("competitor_mean_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("competitor_median_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("competitor_q3_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("competitor_max_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("weighted_market_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("seller_price_difference_from_median", sa.Numeric(12, 2), nullable=True),
        sa.Column("seller_price_percentile", sa.Numeric(5, 2), nullable=True),
        sa.Column("competitor_count", sa.Integer(), nullable=False),
        sa.Column("in_stock_competitor_count", sa.Integer(), nullable=False),
        sa.Column("inventory_position", sa.Integer(), nullable=True),
        sa.Column("inventory_risk_level", sa.String(length=20), nullable=True),
        sa.Column("daily_sales_rate", sa.Numeric(12, 4), nullable=True),
        sa.Column("recent_net_sales", sa.Integer(), nullable=True),
        sa.Column("product_age_days", sa.Integer(), nullable=True),
        sa.Column("promotion_state", sa.String(length=80), nullable=True),
        sa.Column("demand_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("demand_data_status", pricing_analytics_data_status, nullable=False),
        sa.Column("data_status", pricing_analytics_data_status, nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("calculation_version", sa.String(length=40), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("competitor_count >= 0", name="ck_pricing_analytics_competitor_count_nonnegative"),
        sa.CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_pricing_analytics_confidence_range"),
        sa.CheckConstraint("current_price >= 0", name="ck_pricing_analytics_current_price_nonnegative"),
        sa.CheckConstraint("demand_score IS NULL OR (demand_score >= 0 AND demand_score <= 100)", name="ck_pricing_analytics_demand_score_range"),
        sa.CheckConstraint("fixed_fee_amount >= 0", name="ck_pricing_analytics_fixed_fee_nonnegative"),
        sa.CheckConstraint("in_stock_competitor_count >= 0", name="ck_pricing_analytics_in_stock_count_nonnegative"),
        sa.CheckConstraint("minimum_safe_price >= 0", name="ck_pricing_analytics_minimum_safe_price_nonnegative"),
        sa.CheckConstraint("percentage_fee_rate >= 0 AND percentage_fee_rate < 1", name="ck_pricing_analytics_fee_rate"),
        sa.CheckConstraint("seller_price_percentile IS NULL OR (seller_price_percentile >= 0 AND seller_price_percentile <= 100)", name="ck_pricing_analytics_percentile_range"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_pricing_analytics_unit_cost_nonnegative"),
        sa.ForeignKeyConstraint(["competitor_scrape_run_id"], ["scrape_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["fee_policy_id"], ["marketplace_fee_policies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["inventory_snapshot_id"], ["inventory_history.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sales_velocity_id"], ["sales_velocity.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_pricing_analytics_dedupe_key"),
    )
    op.create_index("ix_pricing_analytics_product_calculated", "pricing_analytics_snapshots", ["product_id", "calculated_at"])
    op.create_index("ix_pricing_analytics_seller_calculated", "pricing_analytics_snapshots", ["seller_id", "calculated_at"])
    op.create_index("ix_pricing_analytics_status_calculated", "pricing_analytics_snapshots", ["data_status", "calculated_at"])


def downgrade() -> None:
    op.drop_index("ix_pricing_analytics_status_calculated", table_name="pricing_analytics_snapshots")
    op.drop_index("ix_pricing_analytics_seller_calculated", table_name="pricing_analytics_snapshots")
    op.drop_index("ix_pricing_analytics_product_calculated", table_name="pricing_analytics_snapshots")
    op.drop_table("pricing_analytics_snapshots")
    pricing_analytics_data_status.drop(op.get_bind(), checkfirst=True)
