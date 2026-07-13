"""add transactional RAG index outbox

Revision ID: g1a2b3c4d5e6
Revises: f8a9b0c1d2e3
Create Date: 2026-07-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "g1a2b3c4d5e6"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


ACTION_VALUES = ("UPSERT", "DELETE")
STATUS_VALUES = ("PENDING", "PROCESSING", "COMPLETED", "FAILED", "DEAD_LETTER")
SOURCE_TYPE_VALUES = (
    "COMPETITOR_HISTORY",
    "PRICE_HISTORY",
    "INVENTORY_HISTORY",
    "INVENTORY_LIFECYCLE",
    "SALES_HISTORY",
    "SALES_REVENUE_SUMMARY",
    "RECOMMENDATION",
    "RECOMMENDATION_HISTORY",
    "ALERT",
    "ALERT_HISTORY",
    "PROMOTION_PLAN",
    "PROMOTION_RESULT",
    "SELLER_PRICE_HISTORY",
    "DEAD_STOCK",
    "DEAD_STOCK_HISTORY",
    "SEO",
    "SEO_VISIBILITY_HISTORY",
    "PRICING_HISTORY",
    "COPILOT_HISTORY",
    "ACTION_CENTER",
    "SUPPORT_LOG",
    "PRODUCT_PROFILE",
    "CUSTOMER_CONTEXT",
)

action_enum = postgresql.ENUM(*ACTION_VALUES, name="rag_index_outbox_action", create_type=False)
status_enum = postgresql.ENUM(*STATUS_VALUES, name="rag_index_outbox_status", create_type=False)
source_enum = postgresql.ENUM(*SOURCE_TYPE_VALUES, name="rag_memory_source_type", create_type=False)
action_column_type = sa.Enum(*ACTION_VALUES, name="rag_index_outbox_action", native_enum=False).with_variant(action_enum, "postgresql")
status_column_type = sa.Enum(*STATUS_VALUES, name="rag_index_outbox_status", native_enum=False).with_variant(status_enum, "postgresql")
source_column_type = sa.Enum(*SOURCE_TYPE_VALUES, name="rag_memory_source_type", native_enum=False).with_variant(source_enum, "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        action_enum.create(bind, checkfirst=True)
        status_enum.create(bind, checkfirst=True)

    if "rag_index_outbox" in sa.inspect(bind).get_table_names():
        return

    op.create_table(
        "rag_index_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", source_column_type, nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", action_column_type, nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", status_column_type, nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_summary", sa.String(length=255), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_rag_index_outbox_dedupe_key"),
        sa.CheckConstraint("attempts >= 0", name="ck_rag_index_outbox_attempts_nonnegative"),
    )
    op.create_index(
        "ix_rag_index_outbox_status_next_attempt",
        "rag_index_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_index("ix_rag_index_outbox_seller_id", "rag_index_outbox", ["seller_id"])
    op.create_index("ix_rag_index_outbox_source", "rag_index_outbox", ["source_type", "source_id"])
    op.create_index("ix_rag_index_outbox_created_at", "rag_index_outbox", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if "rag_index_outbox" in sa.inspect(bind).get_table_names():
        op.drop_index("ix_rag_index_outbox_created_at", table_name="rag_index_outbox")
        op.drop_index("ix_rag_index_outbox_source", table_name="rag_index_outbox")
        op.drop_index("ix_rag_index_outbox_seller_id", table_name="rag_index_outbox")
        op.drop_index("ix_rag_index_outbox_status_next_attempt", table_name="rag_index_outbox")
        op.drop_table("rag_index_outbox")
    if bind.dialect.name == "postgresql":
        status_enum.drop(bind, checkfirst=True)
        action_enum.drop(bind, checkfirst=True)
