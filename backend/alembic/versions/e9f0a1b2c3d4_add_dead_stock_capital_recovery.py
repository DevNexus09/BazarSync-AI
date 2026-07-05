"""add dead stock capital recovery estimates

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-07-03 00:00:03.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

METHOD_VALUES = (
    "HISTORICAL_DEMAND_RESPONSE",
    "PRODUCT_PROMOTION_HISTORY",
    "CATEGORY_PROMOTION_HISTORY",
    "CONSERVATIVE_HEURISTIC",
    "INSUFFICIENT_DATA",
)
STATUS_VALUES = ("CALCULATED", "HEURISTIC", "LIMITED_DATA", "INSUFFICIENT_DATA", "BLOCKED_BY_MARGIN_POLICY")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "capital_recovery_estimation_method" not in enum_names:
        postgresql.ENUM(*METHOD_VALUES, name="capital_recovery_estimation_method").create(bind, checkfirst=True)
    if "capital_recovery_estimate_status" not in enum_names:
        postgresql.ENUM(*STATUS_VALUES, name="capital_recovery_estimate_status").create(bind, checkfirst=True)

    if "dead_stock_capital_recovery_estimates" not in set(inspector.get_table_names()):
        op.create_table(
            "dead_stock_capital_recovery_estimates",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("dead_stock_assessment_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("recovery_recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("eligible_quantity", sa.Integer(), nullable=False),
            sa.Column("unit_cost", sa.Numeric(12, 2), nullable=True),
            sa.Column("locked_capital", sa.Numeric(12, 2), nullable=True),
            sa.Column("candidate_price", sa.Numeric(12, 2), nullable=True),
            sa.Column("expected_units_low", sa.Numeric(12, 4), nullable=True),
            sa.Column("expected_units", sa.Numeric(12, 4), nullable=True),
            sa.Column("expected_units_high", sa.Numeric(12, 4), nullable=True),
            sa.Column("gross_recovered_cash_low", sa.Numeric(12, 2), nullable=True),
            sa.Column("gross_recovered_cash", sa.Numeric(12, 2), nullable=True),
            sa.Column("gross_recovered_cash_high", sa.Numeric(12, 2), nullable=True),
            sa.Column("net_cash_recovered", sa.Numeric(12, 2), nullable=True),
            sa.Column("contribution_recovered", sa.Numeric(12, 2), nullable=True),
            sa.Column("cost_basis_recovered", sa.Numeric(12, 2), nullable=True),
            sa.Column("remaining_locked_capital", sa.Numeric(12, 2), nullable=True),
            sa.Column("capital_recovery_ratio", sa.Numeric(7, 6), nullable=True),
            sa.Column("estimation_method", postgresql.ENUM(*METHOD_VALUES, name="capital_recovery_estimation_method", create_type=False), nullable=False),
            sa.Column("estimate_status", postgresql.ENUM(*STATUS_VALUES, name="capital_recovery_estimate_status", create_type=False), nullable=False),
            sa.Column("confidence_score", sa.Numeric(5, 2), nullable=False),
            sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("calculation_version", sa.String(length=20), nullable=False),
            sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["dead_stock_assessment_id"], ["dead_stock_assessments.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["recovery_recommendation_id"], ["dead_stock_recovery_recommendations.id"], ondelete="SET NULL"),
            sa.CheckConstraint("eligible_quantity >= 0", name="ck_capital_recovery_eligible_quantity"),
            sa.CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="ck_capital_recovery_unit_cost"),
            sa.CheckConstraint("locked_capital IS NULL OR locked_capital >= 0", name="ck_capital_recovery_locked"),
            sa.CheckConstraint("candidate_price IS NULL OR candidate_price >= 0", name="ck_capital_recovery_candidate_price"),
            sa.CheckConstraint("expected_units_low IS NULL OR expected_units_low >= 0", name="ck_capital_recovery_low_units"),
            sa.CheckConstraint("expected_units IS NULL OR expected_units >= 0", name="ck_capital_recovery_units"),
            sa.CheckConstraint("expected_units_high IS NULL OR expected_units_high >= 0", name="ck_capital_recovery_high_units"),
            sa.CheckConstraint("gross_recovered_cash_low IS NULL OR gross_recovered_cash_low >= 0", name="ck_capital_recovery_gross_low"),
            sa.CheckConstraint("gross_recovered_cash IS NULL OR gross_recovered_cash >= 0", name="ck_capital_recovery_gross"),
            sa.CheckConstraint("gross_recovered_cash_high IS NULL OR gross_recovered_cash_high >= 0", name="ck_capital_recovery_gross_high"),
            sa.CheckConstraint("remaining_locked_capital IS NULL OR remaining_locked_capital >= 0", name="ck_capital_recovery_remaining"),
            sa.CheckConstraint("capital_recovery_ratio IS NULL OR capital_recovery_ratio <= 1", name="ck_capital_recovery_ratio"),
            sa.CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_capital_recovery_confidence"),
        )
        op.create_index("ix_capital_recovery_seller_product_calculated", "dead_stock_capital_recovery_estimates", ["seller_id", "product_id", "calculated_at"])
        op.create_index("ix_capital_recovery_status", "dead_stock_capital_recovery_estimates", ["estimate_status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dead_stock_capital_recovery_estimates" in set(inspector.get_table_names()):
        op.drop_index("ix_capital_recovery_status", table_name="dead_stock_capital_recovery_estimates")
        op.drop_index("ix_capital_recovery_seller_product_calculated", table_name="dead_stock_capital_recovery_estimates")
        op.drop_table("dead_stock_capital_recovery_estimates")
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    for enum_name in ("capital_recovery_estimate_status", "capital_recovery_estimation_method"):
        if enum_name in enum_names:
            postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
