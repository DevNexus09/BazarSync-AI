"""add sales velocity

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-06-29 00:00:05.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SALES_STATUS_VALUES = ("PENDING", "COMPLETED", "FULFILLED", "CANCELLED", "FAILED_PAYMENT")
DATA_STATUS_VALUES = ("SUFFICIENT", "LIMITED", "INSUFFICIENT")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "sales_record_status" not in enum_names:
        postgresql.ENUM(*SALES_STATUS_VALUES, name="sales_record_status").create(bind, checkfirst=True)
    if "sales_velocity_data_status" not in enum_names:
        postgresql.ENUM(*DATA_STATUS_VALUES, name="sales_velocity_data_status").create(bind, checkfirst=True)

    table_names = set(inspector.get_table_names())
    if "sales_records" not in table_names:
        op.create_table(
            "sales_records",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("source_reference", sa.String(length=255), nullable=False),
            sa.Column("status", postgresql.ENUM(*SALES_STATUS_VALUES, name="sales_record_status", create_type=False), nullable=False),
            sa.Column("sold_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("quantity_sold", sa.Integer(), nullable=False),
            sa.Column("returned_units", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("refunded_restocked_units", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_test_order", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("seller_id", "source_reference", name="uq_sales_records_seller_source_reference"),
            sa.CheckConstraint("quantity_sold >= 0", name="ck_sales_records_quantity_sold_nonnegative"),
            sa.CheckConstraint("returned_units >= 0", name="ck_sales_records_returned_units_nonnegative"),
            sa.CheckConstraint("refunded_restocked_units >= 0", name="ck_sales_records_refunded_restocked_nonnegative"),
        )
        op.create_index("ix_sales_records_product_sold_at", "sales_records", ["product_id", "sold_at"])
        op.create_index("ix_sales_records_seller_sold_at", "sales_records", ["seller_id", "sold_at"])
        op.create_index("ix_sales_records_status_sold_at", "sales_records", ["status", "sold_at"])

    if "sales_velocity" not in table_names:
        op.create_table(
            "sales_velocity",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("as_of_date", sa.Date(), nullable=False),
            sa.Column("window_days", sa.Integer(), nullable=False),
            sa.Column("observed_days", sa.Integer(), nullable=False),
            sa.Column("gross_units_sold", sa.Integer(), nullable=False),
            sa.Column("returned_units", sa.Integer(), nullable=False),
            sa.Column("net_units_sold", sa.Integer(), nullable=False),
            sa.Column("daily_sales_rate", sa.Numeric(precision=12, scale=4), nullable=False),
            sa.Column("sales_days", sa.Integer(), nullable=False),
            sa.Column("confidence_score", sa.Numeric(precision=5, scale=2), nullable=False),
            sa.Column("data_status", postgresql.ENUM(*DATA_STATUS_VALUES, name="sales_velocity_data_status", create_type=False), nullable=False),
            sa.Column("calculation_version", sa.String(length=20), nullable=False),
            sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("product_id", "as_of_date", "window_days", "calculation_version", name="uq_sales_velocity_product_date_window_version"),
            sa.CheckConstraint("window_days > 0", name="ck_sales_velocity_window_days_positive"),
            sa.CheckConstraint("observed_days >= 1", name="ck_sales_velocity_observed_days_positive"),
            sa.CheckConstraint("gross_units_sold >= 0", name="ck_sales_velocity_gross_nonnegative"),
            sa.CheckConstraint("returned_units >= 0", name="ck_sales_velocity_returned_nonnegative"),
            sa.CheckConstraint("net_units_sold >= 0", name="ck_sales_velocity_net_nonnegative"),
            sa.CheckConstraint("daily_sales_rate >= 0", name="ck_sales_velocity_rate_nonnegative"),
            sa.CheckConstraint("sales_days >= 0", name="ck_sales_velocity_sales_days_nonnegative"),
            sa.CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_sales_velocity_confidence_range"),
        )
        op.create_index("ix_sales_velocity_product_as_of_date", "sales_velocity", ["product_id", "as_of_date"])
        op.create_index("ix_sales_velocity_seller_as_of_date", "sales_velocity", ["seller_id", "as_of_date"])
        op.create_index("ix_sales_velocity_product_calculated", "sales_velocity", ["product_id", "calculated_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "sales_velocity" in table_names:
        op.drop_index("ix_sales_velocity_product_calculated", table_name="sales_velocity")
        op.drop_index("ix_sales_velocity_seller_as_of_date", table_name="sales_velocity")
        op.drop_index("ix_sales_velocity_product_as_of_date", table_name="sales_velocity")
        op.drop_table("sales_velocity")
    if "sales_records" in table_names:
        op.drop_index("ix_sales_records_status_sold_at", table_name="sales_records")
        op.drop_index("ix_sales_records_seller_sold_at", table_name="sales_records")
        op.drop_index("ix_sales_records_product_sold_at", table_name="sales_records")
        op.drop_table("sales_records")

    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "sales_velocity_data_status" in enum_names:
        postgresql.ENUM(name="sales_velocity_data_status").drop(bind, checkfirst=True)
    if "sales_record_status" in enum_names:
        postgresql.ENUM(name="sales_record_status").drop(bind, checkfirst=True)
