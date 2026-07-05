"""add inventory aging snapshots

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-07-03 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, Sequence[str], None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AGE_SOURCE_VALUES = (
    "INVENTORY_LOT",
    "PURCHASE_RECEIPT",
    "INVENTORY_TRANSACTION",
    "FIRST_POSITIVE_SNAPSHOT",
    "PRODUCT_CREATED_AT_ESTIMATE",
    "UNAVAILABLE",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "inventory_age_source" not in enum_names:
        postgresql.ENUM(*AGE_SOURCE_VALUES, name="inventory_age_source").create(bind, checkfirst=True)

    if "inventory_aging_snapshots" not in set(inspector.get_table_names()):
        op.create_table(
            "inventory_aging_snapshots",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("inventory_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("as_of_date", sa.Date(), nullable=False),
            sa.Column("quantity_on_hand", sa.Integer(), nullable=False),
            sa.Column("quantity_reserved", sa.Integer(), nullable=False),
            sa.Column("quantity_available", sa.Integer(), nullable=False),
            sa.Column("eligible_unsold_quantity", sa.Integer(), nullable=False),
            sa.Column("oldest_age_days", sa.Integer(), nullable=True),
            sa.Column("newest_age_days", sa.Integer(), nullable=True),
            sa.Column("weighted_average_age_days", sa.Numeric(precision=12, scale=4), nullable=True),
            sa.Column("age_source", postgresql.ENUM(*AGE_SOURCE_VALUES, name="inventory_age_source", create_type=False), nullable=False),
            sa.Column("is_estimated", sa.Boolean(), nullable=False),
            sa.Column("confidence_score", sa.Numeric(precision=5, scale=2), nullable=False),
            sa.Column("age_buckets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("calculation_version", sa.String(length=20), nullable=False),
            sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["inventory_snapshot_id"], ["inventory_history.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("product_id", "as_of_date", "calculation_version", name="uq_inventory_aging_product_date_version"),
            sa.CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_aging_on_hand_nonnegative"),
            sa.CheckConstraint("quantity_reserved >= 0", name="ck_inventory_aging_reserved_nonnegative"),
            sa.CheckConstraint("quantity_available >= 0", name="ck_inventory_aging_available_nonnegative"),
            sa.CheckConstraint("eligible_unsold_quantity >= 0", name="ck_inventory_aging_eligible_nonnegative"),
            sa.CheckConstraint("oldest_age_days IS NULL OR oldest_age_days >= 0", name="ck_inventory_aging_oldest_nonnegative"),
            sa.CheckConstraint("newest_age_days IS NULL OR newest_age_days >= 0", name="ck_inventory_aging_newest_nonnegative"),
            sa.CheckConstraint(
                "weighted_average_age_days IS NULL OR weighted_average_age_days >= 0",
                name="ck_inventory_aging_weighted_nonnegative",
            ),
            sa.CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_inventory_aging_confidence_range"),
        )
        op.create_index("ix_inventory_aging_seller_as_of_date", "inventory_aging_snapshots", ["seller_id", "as_of_date"])
        op.create_index("ix_inventory_aging_product_as_of_date", "inventory_aging_snapshots", ["product_id", "as_of_date"])
        op.create_index("ix_inventory_aging_product_calculated", "inventory_aging_snapshots", ["product_id", "calculated_at"])
        op.create_index("ix_inventory_aging_oldest_age", "inventory_aging_snapshots", ["oldest_age_days"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventory_aging_snapshots" in set(inspector.get_table_names()):
        op.drop_index("ix_inventory_aging_oldest_age", table_name="inventory_aging_snapshots")
        op.drop_index("ix_inventory_aging_product_calculated", table_name="inventory_aging_snapshots")
        op.drop_index("ix_inventory_aging_product_as_of_date", table_name="inventory_aging_snapshots")
        op.drop_index("ix_inventory_aging_seller_as_of_date", table_name="inventory_aging_snapshots")
        op.drop_table("inventory_aging_snapshots")
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "inventory_age_source" in enum_names:
        postgresql.ENUM(name="inventory_age_source").drop(bind, checkfirst=True)
