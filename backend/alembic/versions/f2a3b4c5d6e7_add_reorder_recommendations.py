"""add reorder recommendations

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-29 00:00:07.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ACTION_VALUES = ("HOLD", "REORDER")
STATUS_VALUES = ("OPEN", "ACKNOWLEDGED", "ORDERED", "DISMISSED", "EXPIRED", "INSUFFICIENT_DATA")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "reorder_recommendation_action" not in enum_names:
        postgresql.ENUM(*ACTION_VALUES, name="reorder_recommendation_action").create(bind, checkfirst=True)
    if "reorder_recommendation_status" not in enum_names:
        postgresql.ENUM(*STATUS_VALUES, name="reorder_recommendation_status").create(bind, checkfirst=True)

    if "reorder_recommendations" not in set(inspector.get_table_names()):
        op.create_table(
            "reorder_recommendations",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("inventory_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("sales_velocity_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("stockout_prediction_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("as_of_date", sa.Date(), nullable=False),
            sa.Column("action", postgresql.ENUM(*ACTION_VALUES, name="reorder_recommendation_action", create_type=False), nullable=False),
            sa.Column("recommended_quantity", sa.Integer(), nullable=False),
            sa.Column("reorder_deadline", sa.Date(), nullable=True),
            sa.Column("supplier_lead_time_days", sa.Integer(), nullable=False),
            sa.Column("safety_buffer_days", sa.Integer(), nullable=False),
            sa.Column("review_period_days", sa.Integer(), nullable=False),
            sa.Column("reorder_point", sa.Integer(), nullable=False),
            sa.Column("target_stock", sa.Integer(), nullable=False),
            sa.Column("inventory_position", sa.Integer(), nullable=False),
            sa.Column("daily_sales_rate", sa.Numeric(precision=12, scale=4), nullable=False),
            sa.Column("confidence_score", sa.Numeric(precision=5, scale=2), nullable=False),
            sa.Column("recommendation_status", postgresql.ENUM(*STATUS_VALUES, name="reorder_recommendation_status", create_type=False), nullable=False),
            sa.Column("explanation", sa.Text(), nullable=False),
            sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("calculation_version", sa.String(length=20), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["inventory_snapshot_id"], ["inventory_history.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["sales_velocity_id"], ["sales_velocity.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["stockout_prediction_id"], ["stockout_predictions.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("product_id", "as_of_date", "calculation_version", name="uq_reorder_recommendations_product_date_version"),
            sa.CheckConstraint("recommended_quantity >= 0", name="ck_reorder_recommendations_quantity_nonnegative"),
            sa.CheckConstraint("supplier_lead_time_days >= 0", name="ck_reorder_recommendations_lead_nonnegative"),
            sa.CheckConstraint("safety_buffer_days >= 0", name="ck_reorder_recommendations_buffer_nonnegative"),
            sa.CheckConstraint("review_period_days >= 0", name="ck_reorder_recommendations_review_nonnegative"),
            sa.CheckConstraint("reorder_point >= 0", name="ck_reorder_recommendations_point_nonnegative"),
            sa.CheckConstraint("target_stock >= 0", name="ck_reorder_recommendations_target_nonnegative"),
            sa.CheckConstraint("daily_sales_rate >= 0", name="ck_reorder_recommendations_rate_nonnegative"),
            sa.CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_reorder_recommendations_confidence_range"),
        )
        op.create_index("ix_reorder_recommendations_product_as_of_date", "reorder_recommendations", ["product_id", "as_of_date"])
        op.create_index("ix_reorder_recommendations_seller_status", "reorder_recommendations", ["seller_id", "recommendation_status"])
        op.create_index("ix_reorder_recommendations_deadline", "reorder_recommendations", ["reorder_deadline"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "reorder_recommendations" in set(inspector.get_table_names()):
        op.drop_index("ix_reorder_recommendations_deadline", table_name="reorder_recommendations")
        op.drop_index("ix_reorder_recommendations_seller_status", table_name="reorder_recommendations")
        op.drop_index("ix_reorder_recommendations_product_as_of_date", table_name="reorder_recommendations")
        op.drop_table("reorder_recommendations")
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "reorder_recommendation_status" in enum_names:
        postgresql.ENUM(name="reorder_recommendation_status").drop(bind, checkfirst=True)
    if "reorder_recommendation_action" in enum_names:
        postgresql.ENUM(name="reorder_recommendation_action").drop(bind, checkfirst=True)
