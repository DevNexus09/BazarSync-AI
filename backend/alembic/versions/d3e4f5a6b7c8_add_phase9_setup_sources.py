"""add phase9 setup sources

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-07-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_stock_in",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_inventory_stock_in_quantity_positive"),
        sa.CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="ck_inventory_stock_in_unit_cost_nonnegative"),
        sa.UniqueConstraint("seller_id", "source_reference", name="uq_inventory_stock_in_seller_source_reference"),
    )
    op.create_index("ix_inventory_stock_in_product_received", "inventory_stock_in", ["product_id", "received_at"])
    op.create_index("ix_inventory_stock_in_seller_received", "inventory_stock_in", ["seller_id", "received_at"])

    op.create_table(
        "product_visibility_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marketplace", sa.String(length=120), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("search_rank", sa.Integer(), nullable=True),
        sa.Column("listing_quality_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("conversion_rate", sa.Numeric(7, 6), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False, server_default="manual"),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("impressions >= 0", name="ck_visibility_impressions_nonnegative"),
        sa.CheckConstraint("views >= 0", name="ck_visibility_views_nonnegative"),
        sa.CheckConstraint("clicks >= 0", name="ck_visibility_clicks_nonnegative"),
        sa.CheckConstraint("search_rank IS NULL OR search_rank > 0", name="ck_visibility_search_rank_positive"),
        sa.CheckConstraint("listing_quality_score IS NULL OR (listing_quality_score >= 0 AND listing_quality_score <= 100)", name="ck_visibility_quality_score_range"),
        sa.CheckConstraint("conversion_rate IS NULL OR (conversion_rate >= 0 AND conversion_rate <= 1)", name="ck_visibility_conversion_rate_range"),
        sa.UniqueConstraint("product_id", "marketplace", "metric_date", "source", name="uq_visibility_product_marketplace_date_source"),
    )
    op.create_index("ix_visibility_product_metric_date", "product_visibility_metrics", ["product_id", "metric_date"])
    op.create_index("ix_visibility_seller_metric_date", "product_visibility_metrics", ["seller_id", "metric_date"])


def downgrade() -> None:
    op.drop_index("ix_visibility_seller_metric_date", table_name="product_visibility_metrics")
    op.drop_index("ix_visibility_product_metric_date", table_name="product_visibility_metrics")
    op.drop_table("product_visibility_metrics")
    op.drop_index("ix_inventory_stock_in_seller_received", table_name="inventory_stock_in")
    op.drop_index("ix_inventory_stock_in_product_received", table_name="inventory_stock_in")
    op.drop_table("inventory_stock_in")
