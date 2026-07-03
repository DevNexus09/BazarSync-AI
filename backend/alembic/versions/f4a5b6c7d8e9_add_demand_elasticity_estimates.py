"""add demand elasticity estimates

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-07-01 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


demand_estimation_method = postgresql.ENUM(
    "HISTORICAL_ELASTICITY",
    "CATEGORY_PRIOR",
    "CONSERVATIVE_HEURISTIC",
    "INSUFFICIENT_DATA",
    name="demand_estimation_method",
    create_type=False,
)
demand_estimate_data_status = postgresql.ENUM(
    "SUFFICIENT",
    "LIMITED",
    "INSUFFICIENT",
    "STALE",
    name="demand_estimate_data_status",
    create_type=False,
)


def upgrade() -> None:
    demand_estimation_method.create(op.get_bind(), checkfirst=True)
    demand_estimate_data_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "demand_elasticity_estimates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("seller_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("estimation_method", demand_estimation_method, nullable=False),
        sa.Column("elasticity", sa.Numeric(10, 6), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("baseline_units", sa.Numeric(12, 4), nullable=True),
        sa.Column("observation_start", sa.Date(), nullable=True),
        sa.Column("observation_end", sa.Date(), nullable=True),
        sa.Column("quality_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=False),
        sa.Column("data_status", demand_estimate_data_status, nullable=False),
        sa.Column("calculation_version", sa.String(length=40), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("baseline_units IS NULL OR baseline_units >= 0", name="ck_demand_elasticity_baseline_nonnegative"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_demand_elasticity_confidence_range"),
        sa.CheckConstraint("sample_count >= 0", name="ck_demand_elasticity_sample_count_nonnegative"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "product_id", "observation_end", "calculation_version", name="uq_demand_elasticity_scope_end_version"),
    )
    op.create_index("ix_demand_elasticity_method_calculated", "demand_elasticity_estimates", ["estimation_method", "calculated_at"])
    op.create_index("ix_demand_elasticity_product_calculated", "demand_elasticity_estimates", ["product_id", "calculated_at"])
    op.create_index("ix_demand_elasticity_seller_calculated", "demand_elasticity_estimates", ["seller_id", "calculated_at"])


def downgrade() -> None:
    op.drop_index("ix_demand_elasticity_seller_calculated", table_name="demand_elasticity_estimates")
    op.drop_index("ix_demand_elasticity_product_calculated", table_name="demand_elasticity_estimates")
    op.drop_index("ix_demand_elasticity_method_calculated", table_name="demand_elasticity_estimates")
    op.drop_table("demand_elasticity_estimates")
    demand_estimate_data_status.drop(op.get_bind(), checkfirst=True)
    demand_estimation_method.drop(op.get_bind(), checkfirst=True)
