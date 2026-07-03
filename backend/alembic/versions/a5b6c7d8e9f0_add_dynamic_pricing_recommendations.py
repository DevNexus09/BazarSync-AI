"""add dynamic pricing recommendations

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-07-01 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


dynamic_pricing_action = postgresql.ENUM("PRICE_LOWER", "PRICE_RAISE", "HOLD", name="dynamic_pricing_action", create_type=False)
dynamic_pricing_status = postgresql.ENUM("OPEN", "ACKNOWLEDGED", "DISMISSED", "EXPIRED", "SUPERSEDED", "INSUFFICIENT_DATA", name="dynamic_pricing_recommendation_status", create_type=False)
pricing_objective = postgresql.ENUM("MAXIMIZE_EXPECTED_PROFIT", "MAXIMIZE_REVENUE_WITH_MARGIN_FLOOR", "PROTECT_INVENTORY", "CLEAR_EXCESS_STOCK", name="pricing_objective", create_type=False)
demand_estimation_method = postgresql.ENUM("HISTORICAL_ELASTICITY", "CATEGORY_PRIOR", "CONSERVATIVE_HEURISTIC", "INSUFFICIENT_DATA", name="demand_estimation_method", create_type=False)


def upgrade() -> None:
    dynamic_pricing_action.create(op.get_bind(), checkfirst=True)
    dynamic_pricing_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "dynamic_pricing_recommendations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("seller_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("pricing_analytics_id", sa.UUID(), nullable=False),
        sa.Column("elasticity_estimate_id", sa.UUID(), nullable=True),
        sa.Column("action", dynamic_pricing_action, nullable=False),
        sa.Column("current_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("recommended_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("minimum_safe_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("expected_units", sa.Numeric(12, 4), nullable=True),
        sa.Column("expected_revenue", sa.Numeric(14, 2), nullable=True),
        sa.Column("expected_profit", sa.Numeric(14, 2), nullable=True),
        sa.Column("baseline_expected_revenue", sa.Numeric(14, 2), nullable=True),
        sa.Column("baseline_expected_profit", sa.Numeric(14, 2), nullable=True),
        sa.Column("revenue_impact", sa.Numeric(14, 2), nullable=True),
        sa.Column("profit_impact", sa.Numeric(14, 2), nullable=True),
        sa.Column("margin_rate", sa.Numeric(8, 6), nullable=True),
        sa.Column("confidence_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("estimation_method", demand_estimation_method, nullable=False),
        sa.Column("recommendation_status", dynamic_pricing_status, nullable=False),
        sa.Column("objective", pricing_objective, nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("formula_version", sa.String(length=40), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("baseline_expected_revenue IS NULL OR baseline_expected_revenue >= 0", name="ck_dynamic_pricing_baseline_revenue_nonnegative"),
        sa.CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_dynamic_pricing_confidence_range"),
        sa.CheckConstraint("current_price >= 0", name="ck_dynamic_pricing_current_price_nonnegative"),
        sa.CheckConstraint("expected_revenue IS NULL OR expected_revenue >= 0", name="ck_dynamic_pricing_expected_revenue_nonnegative"),
        sa.CheckConstraint("expected_units IS NULL OR expected_units >= 0", name="ck_dynamic_pricing_expected_units_nonnegative"),
        sa.CheckConstraint("minimum_safe_price IS NULL OR minimum_safe_price >= 0", name="ck_dynamic_pricing_safe_price_nonnegative"),
        sa.CheckConstraint("recommended_price >= 0", name="ck_dynamic_pricing_recommended_price_nonnegative"),
        sa.ForeignKeyConstraint(["elasticity_estimate_id"], ["demand_elasticity_estimates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pricing_analytics_id"], ["pricing_analytics_snapshots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "product_id", "pricing_analytics_id", "objective", "formula_version", name="uq_dynamic_pricing_recommendation_snapshot_objective"),
    )
    op.create_index("ix_dynamic_pricing_product_generated", "dynamic_pricing_recommendations", ["product_id", "generated_at"])
    op.create_index("ix_dynamic_pricing_seller_status", "dynamic_pricing_recommendations", ["seller_id", "recommendation_status"])
    op.create_index(
        "uq_dynamic_pricing_active_product_objective",
        "dynamic_pricing_recommendations",
        ["seller_id", "product_id", "objective", "formula_version"],
        unique=True,
        postgresql_where=sa.text("recommendation_status = 'OPEN'"),
    )


def downgrade() -> None:
    op.drop_index("uq_dynamic_pricing_active_product_objective", table_name="dynamic_pricing_recommendations")
    op.drop_index("ix_dynamic_pricing_seller_status", table_name="dynamic_pricing_recommendations")
    op.drop_index("ix_dynamic_pricing_product_generated", table_name="dynamic_pricing_recommendations")
    op.drop_table("dynamic_pricing_recommendations")
    dynamic_pricing_status.drop(op.get_bind(), checkfirst=True)
    dynamic_pricing_action.drop(op.get_bind(), checkfirst=True)
