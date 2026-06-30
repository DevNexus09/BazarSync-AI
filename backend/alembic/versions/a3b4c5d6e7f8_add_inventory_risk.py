"""add inventory risk assessments

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-06-29 00:00:08.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEVEL_VALUES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
DATA_STATUS_VALUES = ("SUFFICIENT", "LIMITED", "INSUFFICIENT")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "inventory_risk_level" not in enum_names:
        postgresql.ENUM(*LEVEL_VALUES, name="inventory_risk_level").create(bind, checkfirst=True)
    if "inventory_risk_data_status" not in enum_names:
        postgresql.ENUM(*DATA_STATUS_VALUES, name="inventory_risk_data_status").create(bind, checkfirst=True)

    if "inventory_risk_assessments" not in set(inspector.get_table_names()):
        op.create_table(
            "inventory_risk_assessments",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("stockout_prediction_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("reorder_recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("as_of_date", sa.Date(), nullable=False),
            sa.Column("risk_score", sa.Numeric(precision=5, scale=2), nullable=False),
            sa.Column("risk_level", postgresql.ENUM(*LEVEL_VALUES, name="inventory_risk_level", create_type=False), nullable=True),
            sa.Column("coverage_gap_days", sa.Numeric(precision=12, scale=4), nullable=True),
            sa.Column("data_status", postgresql.ENUM(*DATA_STATUS_VALUES, name="inventory_risk_data_status", create_type=False), nullable=False),
            sa.Column("confidence_score", sa.Numeric(precision=5, scale=2), nullable=False),
            sa.Column("factors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("calculation_version", sa.String(length=20), nullable=False),
            sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["stockout_prediction_id"], ["stockout_predictions.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["reorder_recommendation_id"], ["reorder_recommendations.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("product_id", "as_of_date", "calculation_version", name="uq_inventory_risk_product_date_version"),
            sa.CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="ck_inventory_risk_score_range"),
            sa.CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_inventory_risk_confidence_range"),
        )
        op.create_index("ix_inventory_risk_seller_level", "inventory_risk_assessments", ["seller_id", "risk_level"])
        op.create_index("ix_inventory_risk_product_as_of_date", "inventory_risk_assessments", ["product_id", "as_of_date"])
        op.create_index("ix_inventory_risk_assessed_at", "inventory_risk_assessments", ["assessed_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventory_risk_assessments" in set(inspector.get_table_names()):
        op.drop_index("ix_inventory_risk_assessed_at", table_name="inventory_risk_assessments")
        op.drop_index("ix_inventory_risk_product_as_of_date", table_name="inventory_risk_assessments")
        op.drop_index("ix_inventory_risk_seller_level", table_name="inventory_risk_assessments")
        op.drop_table("inventory_risk_assessments")
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "inventory_risk_data_status" in enum_names:
        postgresql.ENUM(name="inventory_risk_data_status").drop(bind, checkfirst=True)
    if "inventory_risk_level" in enum_names:
        postgresql.ENUM(name="inventory_risk_level").drop(bind, checkfirst=True)
