"""add stockout predictions

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-06-29 00:00:06.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STATUS_VALUES = ("PREDICTED", "ALREADY_OUT_OF_STOCK", "NO_RECENT_DEMAND", "INSUFFICIENT_DATA")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "stockout_prediction_status" not in enum_names:
        postgresql.ENUM(*STATUS_VALUES, name="stockout_prediction_status").create(bind, checkfirst=True)

    if "stockout_predictions" not in set(inspector.get_table_names()):
        op.create_table(
            "stockout_predictions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("inventory_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("sales_velocity_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("as_of_date", sa.Date(), nullable=False),
            sa.Column("quantity_on_hand", sa.Integer(), nullable=False),
            sa.Column("quantity_reserved", sa.Integer(), nullable=False),
            sa.Column("quantity_incoming", sa.Integer(), nullable=False),
            sa.Column("inventory_position", sa.Integer(), nullable=False),
            sa.Column("daily_sales_rate", sa.Numeric(precision=12, scale=4), nullable=False),
            sa.Column("days_remaining", sa.Numeric(precision=12, scale=4), nullable=False),
            sa.Column("predicted_stockout_date", sa.Date(), nullable=True),
            sa.Column("prediction_status", postgresql.ENUM(*STATUS_VALUES, name="stockout_prediction_status", create_type=False), nullable=False),
            sa.Column("confidence_score", sa.Numeric(precision=5, scale=2), nullable=False),
            sa.Column("calculation_version", sa.String(length=20), nullable=False),
            sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("explanation", sa.String(length=500), nullable=False),
            sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["inventory_snapshot_id"], ["inventory_history.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["sales_velocity_id"], ["sales_velocity.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("product_id", "as_of_date", "calculation_version", name="uq_stockout_predictions_product_date_version"),
            sa.CheckConstraint("daily_sales_rate >= 0", name="ck_stockout_predictions_rate_nonnegative"),
            sa.CheckConstraint("days_remaining >= 0", name="ck_stockout_predictions_days_nonnegative"),
            sa.CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_stockout_predictions_confidence_range"),
        )
        op.create_index("ix_stockout_predictions_product_as_of_date", "stockout_predictions", ["product_id", "as_of_date"])
        op.create_index("ix_stockout_predictions_seller_as_of_date", "stockout_predictions", ["seller_id", "as_of_date"])
        op.create_index("ix_stockout_predictions_status_as_of_date", "stockout_predictions", ["prediction_status", "as_of_date"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "stockout_predictions" in set(inspector.get_table_names()):
        op.drop_index("ix_stockout_predictions_status_as_of_date", table_name="stockout_predictions")
        op.drop_index("ix_stockout_predictions_seller_as_of_date", table_name="stockout_predictions")
        op.drop_index("ix_stockout_predictions_product_as_of_date", table_name="stockout_predictions")
        op.drop_table("stockout_predictions")
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "stockout_prediction_status" in enum_names:
        postgresql.ENUM(name="stockout_prediction_status").drop(bind, checkfirst=True)
