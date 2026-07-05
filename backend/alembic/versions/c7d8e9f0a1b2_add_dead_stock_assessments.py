"""add dead stock assessments

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-07-03 00:00:01.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CLASSIFICATION_VALUES = ("HEALTHY", "SLOW_MOVING", "AT_RISK", "DEAD_STOCK", "INSUFFICIENT_DATA")
DATA_STATUS_VALUES = ("SUFFICIENT", "LIMITED", "INSUFFICIENT")
NO_SALES_VALUES = (
    "NO_SALES_WITHIN_THRESHOLD",
    "NEVER_SOLD",
    "SALES_DATA_INSUFFICIENT",
    "RECENT_SALE",
    "PRODUCT_TOO_NEW",
)
AGE_STATE_VALUES = ("AGE_THRESHOLD_EXCEEDED", "AGE_BELOW_THRESHOLD", "AGE_ESTIMATED", "AGE_DATA_UNAVAILABLE")
VISIBILITY_VALUES = ("LOW_VISIBILITY", "NORMAL_VISIBILITY", "VISIBILITY_DATA_LIMITED", "VISIBILITY_DATA_UNAVAILABLE")
RISK_LEVEL_VALUES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    enum_specs = {
        "dead_stock_classification": CLASSIFICATION_VALUES,
        "dead_stock_data_status": DATA_STATUS_VALUES,
        "dead_stock_no_sales_state": NO_SALES_VALUES,
        "dead_stock_inventory_age_state": AGE_STATE_VALUES,
        "dead_stock_visibility_status": VISIBILITY_VALUES,
        "dead_stock_risk_level": RISK_LEVEL_VALUES,
    }
    for enum_name, values in enum_specs.items():
        if enum_name not in enum_names:
            postgresql.ENUM(*values, name=enum_name).create(bind, checkfirst=True)

    if "dead_stock_assessments" not in set(inspector.get_table_names()):
        op.create_table(
            "dead_stock_assessments",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("inventory_aging_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("inventory_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("sales_velocity_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("as_of_date", sa.Date(), nullable=False),
            sa.Column("classification", postgresql.ENUM(*CLASSIFICATION_VALUES, name="dead_stock_classification", create_type=False), nullable=False),
            sa.Column("eligible_quantity", sa.Integer(), nullable=False),
            sa.Column("days_since_last_sale", sa.Integer(), nullable=True),
            sa.Column("last_sale_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("inventory_age_days", sa.Integer(), nullable=True),
            sa.Column("inventory_age_is_estimated", sa.Boolean(), nullable=False),
            sa.Column("no_sales_state", postgresql.ENUM(*NO_SALES_VALUES, name="dead_stock_no_sales_state", create_type=False), nullable=False),
            sa.Column("inventory_age_state", postgresql.ENUM(*AGE_STATE_VALUES, name="dead_stock_inventory_age_state", create_type=False), nullable=False),
            sa.Column("visibility_score", sa.Numeric(precision=5, scale=2), nullable=True),
            sa.Column("visibility_status", postgresql.ENUM(*VISIBILITY_VALUES, name="dead_stock_visibility_status", create_type=False), nullable=False),
            sa.Column("risk_score", sa.Numeric(precision=5, scale=2), nullable=False),
            sa.Column("risk_level", postgresql.ENUM(*RISK_LEVEL_VALUES, name="dead_stock_risk_level", create_type=False), nullable=False),
            sa.Column("rule_results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("triggered_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("data_status", postgresql.ENUM(*DATA_STATUS_VALUES, name="dead_stock_data_status", create_type=False), nullable=False),
            sa.Column("confidence_score", sa.Numeric(precision=5, scale=2), nullable=False),
            sa.Column("calculation_version", sa.String(length=20), nullable=False),
            sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["inventory_aging_id"], ["inventory_aging_snapshots.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["inventory_snapshot_id"], ["inventory_history.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["sales_velocity_id"], ["sales_velocity.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("product_id", "as_of_date", "calculation_version", name="uq_dead_stock_product_date_version"),
            sa.CheckConstraint("eligible_quantity >= 0", name="ck_dead_stock_eligible_nonnegative"),
            sa.CheckConstraint("days_since_last_sale IS NULL OR days_since_last_sale >= 0", name="ck_dead_stock_days_since_sale_nonnegative"),
            sa.CheckConstraint("inventory_age_days IS NULL OR inventory_age_days >= 0", name="ck_dead_stock_inventory_age_nonnegative"),
            sa.CheckConstraint("visibility_score IS NULL OR (visibility_score >= 0 AND visibility_score <= 100)", name="ck_dead_stock_visibility_score_range"),
            sa.CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="ck_dead_stock_risk_score_range"),
            sa.CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_dead_stock_confidence_range"),
        )
        op.create_index("ix_dead_stock_seller_classification", "dead_stock_assessments", ["seller_id", "classification"])
        op.create_index("ix_dead_stock_seller_risk_level", "dead_stock_assessments", ["seller_id", "risk_level"])
        op.create_index("ix_dead_stock_product_as_of_date", "dead_stock_assessments", ["product_id", "as_of_date"])
        op.create_index("ix_dead_stock_visibility_status", "dead_stock_assessments", ["visibility_status"])
        op.create_index("ix_dead_stock_data_status", "dead_stock_assessments", ["data_status"])
        op.create_index("ix_dead_stock_assessed_at", "dead_stock_assessments", ["assessed_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dead_stock_assessments" in set(inspector.get_table_names()):
        op.drop_index("ix_dead_stock_assessed_at", table_name="dead_stock_assessments")
        op.drop_index("ix_dead_stock_data_status", table_name="dead_stock_assessments")
        op.drop_index("ix_dead_stock_visibility_status", table_name="dead_stock_assessments")
        op.drop_index("ix_dead_stock_product_as_of_date", table_name="dead_stock_assessments")
        op.drop_index("ix_dead_stock_seller_risk_level", table_name="dead_stock_assessments")
        op.drop_index("ix_dead_stock_seller_classification", table_name="dead_stock_assessments")
        op.drop_table("dead_stock_assessments")

    enum_names = {enum["name"] for enum in inspector.get_enums()}
    for enum_name in (
        "dead_stock_visibility_status",
        "dead_stock_risk_level",
        "dead_stock_inventory_age_state",
        "dead_stock_no_sales_state",
        "dead_stock_data_status",
        "dead_stock_classification",
    ):
        if enum_name in enum_names:
            postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
