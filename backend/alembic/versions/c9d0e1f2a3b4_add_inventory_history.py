"""add inventory history

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-29 00:00:04.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SOURCE_VALUES = ("DAILY_SNAPSHOT", "MANUAL_ADJUSTMENT", "MARKETPLACE_SYNC", "BACKFILL")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "inventory_snapshot_source" not in enum_names:
        postgresql.ENUM(*SOURCE_VALUES, name="inventory_snapshot_source").create(bind, checkfirst=True)

    if "inventory_history" not in set(inspector.get_table_names()):
        op.create_table(
            "inventory_history",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("quantity_on_hand", sa.Integer(), nullable=False),
            sa.Column("quantity_reserved", sa.Integer(), nullable=False),
            sa.Column("quantity_available", sa.Integer(), nullable=False),
            sa.Column("quantity_incoming", sa.Integer(), nullable=False),
            sa.Column(
                "source",
                postgresql.ENUM(*SOURCE_VALUES, name="inventory_snapshot_source", create_type=False),
                nullable=False,
            ),
            sa.Column("source_reference", sa.String(length=255), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("seller_id", "product_id", "snapshot_date", name="uq_inventory_history_seller_product_date"),
            sa.CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_history_on_hand_nonnegative"),
            sa.CheckConstraint("quantity_reserved >= 0", name="ck_inventory_history_reserved_nonnegative"),
            sa.CheckConstraint("quantity_incoming >= 0", name="ck_inventory_history_incoming_nonnegative"),
            sa.CheckConstraint(
                "quantity_available = quantity_on_hand - quantity_reserved",
                name="ck_inventory_history_available_definition",
            ),
        )
        op.create_index("ix_inventory_history_product_snapshot_date", "inventory_history", ["product_id", "snapshot_date"])
        op.create_index("ix_inventory_history_seller_snapshot_date", "inventory_history", ["seller_id", "snapshot_date"])
        op.create_index("ix_inventory_history_product_captured", "inventory_history", ["product_id", "captured_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventory_history" in set(inspector.get_table_names()):
        op.drop_index("ix_inventory_history_product_captured", table_name="inventory_history")
        op.drop_index("ix_inventory_history_seller_snapshot_date", table_name="inventory_history")
        op.drop_index("ix_inventory_history_product_snapshot_date", table_name="inventory_history")
        op.drop_table("inventory_history")
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "inventory_snapshot_source" in enum_names:
        postgresql.ENUM(name="inventory_snapshot_source").drop(bind, checkfirst=True)
