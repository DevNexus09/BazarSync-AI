"""add promotion persistence and seller product price history

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-07-06 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


promotion_plan_status = postgresql.ENUM(
    "PROPOSED",
    "APPROVED",
    "SCHEDULED",
    "RUNNING",
    "COMPLETED",
    "CANCELLED",
    "EXECUTION_NOT_IMPLEMENTED",
    name="promotion_plan_status",
    create_type=False,
)
promotion_result_status = postgresql.ENUM(
    "CALCULATED",
    "PARTIAL",
    "MISSING_DATA",
    "FAILED",
    name="promotion_result_status",
    create_type=False,
)
product_price_history_source = postgresql.ENUM(
    "PRODUCT_EDIT",
    "PRICING_RECOMMENDATION",
    "COPILOT_PROPOSAL",
    "IMPORT",
    "UNKNOWN",
    "BASELINE_CURRENT_PRICE",
    name="product_price_history_source",
    create_type=False,
)


def _json_type():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        promotion_plan_status.create(bind, checkfirst=True)
        promotion_result_status.create(bind, checkfirst=True)
        product_price_history_source.create(bind, checkfirst=True)

    op.create_table(
        "promotion_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("marketplace", sa.String(length=120), nullable=True),
        sa.Column("promotion_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("proposed_discount_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("proposed_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("planned_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", promotion_plan_status, server_default="PROPOSED", nullable=False),
        sa.Column("source", sa.String(length=80), server_default="UNKNOWN", nullable=False),
        sa.Column("created_from_recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_from_copilot_proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("safety_checks_json", _json_type(), nullable=True),
        sa.Column("expected_impact_json", _json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_promotion_plans_seller_id", "promotion_plans", ["seller_id"])
    op.create_index("ix_promotion_plans_product_id", "promotion_plans", ["product_id"])
    op.create_index("ix_promotion_plans_marketplace", "promotion_plans", ["marketplace"])
    op.create_index("ix_promotion_plans_status", "promotion_plans", ["status"])
    op.create_index("ix_promotion_plans_planned_start_at", "promotion_plans", ["planned_start_at"])

    op.create_table(
        "promotion_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("promotion_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("marketplace", sa.String(length=120), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("units_sold", sa.Integer(), nullable=True),
        sa.Column("gross_revenue", sa.Numeric(12, 2), nullable=True),
        sa.Column("estimated_profit", sa.Numeric(12, 2), nullable=True),
        sa.Column("spend", sa.Numeric(12, 2), nullable=True),
        sa.Column("discount_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("roi", sa.Numeric(12, 4), nullable=True),
        sa.Column("result_status", promotion_result_status, server_default="MISSING_DATA", nullable=False),
        sa.Column("evidence_json", _json_type(), nullable=True),
        sa.Column("missing_data_json", _json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["promotion_plan_id"], ["promotion_plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_promotion_results_seller_id", "promotion_results", ["seller_id"])
    op.create_index("ix_promotion_results_product_id", "promotion_results", ["product_id"])
    op.create_index("ix_promotion_results_promotion_plan_id", "promotion_results", ["promotion_plan_id"])
    op.create_index("ix_promotion_results_marketplace", "promotion_results", ["marketplace"])
    op.create_index("ix_promotion_results_started_at", "promotion_results", ["started_at"])
    op.create_index("ix_promotion_results_ended_at", "promotion_results", ["ended_at"])

    op.create_table(
        "product_price_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("marketplace", sa.String(length=120), nullable=True),
        sa.Column("old_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("new_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", product_price_history_source, server_default="UNKNOWN", nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("changed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["product_marketplace_listings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_price_history_seller_id", "product_price_history", ["seller_id"])
    op.create_index("ix_product_price_history_product_id", "product_price_history", ["product_id"])
    op.create_index("ix_product_price_history_listing_id", "product_price_history", ["listing_id"])
    op.create_index("ix_product_price_history_marketplace", "product_price_history", ["marketplace"])
    op.create_index("ix_product_price_history_changed_at", "product_price_history", ["changed_at"])


def downgrade() -> None:
    op.drop_index("ix_product_price_history_changed_at", table_name="product_price_history")
    op.drop_index("ix_product_price_history_marketplace", table_name="product_price_history")
    op.drop_index("ix_product_price_history_listing_id", table_name="product_price_history")
    op.drop_index("ix_product_price_history_product_id", table_name="product_price_history")
    op.drop_index("ix_product_price_history_seller_id", table_name="product_price_history")
    op.drop_table("product_price_history")

    op.drop_index("ix_promotion_results_ended_at", table_name="promotion_results")
    op.drop_index("ix_promotion_results_started_at", table_name="promotion_results")
    op.drop_index("ix_promotion_results_marketplace", table_name="promotion_results")
    op.drop_index("ix_promotion_results_promotion_plan_id", table_name="promotion_results")
    op.drop_index("ix_promotion_results_product_id", table_name="promotion_results")
    op.drop_index("ix_promotion_results_seller_id", table_name="promotion_results")
    op.drop_table("promotion_results")

    op.drop_index("ix_promotion_plans_planned_start_at", table_name="promotion_plans")
    op.drop_index("ix_promotion_plans_status", table_name="promotion_plans")
    op.drop_index("ix_promotion_plans_marketplace", table_name="promotion_plans")
    op.drop_index("ix_promotion_plans_product_id", table_name="promotion_plans")
    op.drop_index("ix_promotion_plans_seller_id", table_name="promotion_plans")
    op.drop_table("promotion_plans")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        product_price_history_source.drop(bind, checkfirst=True)
        promotion_result_status.drop(bind, checkfirst=True)
        promotion_plan_status.drop(bind, checkfirst=True)
