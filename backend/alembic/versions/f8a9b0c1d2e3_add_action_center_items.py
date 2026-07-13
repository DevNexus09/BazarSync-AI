"""add action center items

Revision ID: f8a9b0c1d2e3
Revises: c1d2e3f4a5b7
Create Date: 2026-07-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f8a9b0c1d2e3"
down_revision = "c1d2e3f4a5b7"
branch_labels = None
depends_on = None


priority_enum = postgresql.ENUM("LOW", "MEDIUM", "HIGH", "CRITICAL", name="action_center_priority", create_type=False)
status_enum = postgresql.ENUM("OPEN", "ACKNOWLEDGED", "COMPLETED", "DISMISSED", "EXPIRED", name="action_center_item_status", create_type=False)
priority_column_type = sa.Enum("LOW", "MEDIUM", "HIGH", "CRITICAL", name="action_center_priority", native_enum=False).with_variant(priority_enum, "postgresql")
status_column_type = sa.Enum("OPEN", "ACKNOWLEDGED", "COMPLETED", "DISMISSED", "EXPIRED", name="action_center_item_status", native_enum=False).with_variant(status_enum, "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        priority_enum.create(bind, checkfirst=True)
        status_enum.create(bind, checkfirst=True)

    op.create_table(
        "action_center_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("seller_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("source_domain", sa.String(length=80), nullable=False),
        sa.Column("source_type", sa.String(length=120), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("action_type", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", priority_column_type, nullable=False),
        sa.Column("confidence", sa.String(length=40), nullable=True),
        sa.Column("expected_impact_json", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),
        sa.Column("status", status_column_type, server_default="OPEN", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "source_type", "source_id", name="uq_action_center_items_source"),
    )
    op.create_index("ix_action_center_items_priority_due", "action_center_items", ["priority", "due_at"])
    op.create_index("ix_action_center_items_product_status", "action_center_items", ["product_id", "status"])
    op.create_index("ix_action_center_items_seller_status", "action_center_items", ["seller_id", "status"])
    op.create_index("ix_action_center_items_source", "action_center_items", ["source_type", "source_id"])


def downgrade() -> None:
    op.drop_index("ix_action_center_items_source", table_name="action_center_items")
    op.drop_index("ix_action_center_items_seller_status", table_name="action_center_items")
    op.drop_index("ix_action_center_items_product_status", table_name="action_center_items")
    op.drop_index("ix_action_center_items_priority_due", table_name="action_center_items")
    op.drop_table("action_center_items")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        status_enum.drop(bind, checkfirst=True)
        priority_enum.drop(bind, checkfirst=True)
