"""add business expenses, store metrics, listing ratings and sales customer/district

Revision ID: o9c0d1e2f3a4
Revises: n8b9c0d1e2f3
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "o9c0d1e2f3a4"
down_revision: str | None = "n8b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPENSE_TYPES = ("ADVERTISING", "SHIPPING", "PACKAGING", "SUPPLIER_PURCHASE", "RENT", "SALARY", "UTILITIES", "OTHER")


def upgrade() -> None:
    # Additive only: nullable columns and new tables; existing rows stay readable unchanged.
    op.add_column("sales_records", sa.Column("customer_reference", sa.String(length=64), nullable=True))
    op.add_column("sales_records", sa.Column("delivery_district", sa.String(length=80), nullable=True))
    op.add_column("product_marketplace_listings", sa.Column("rating", sa.Numeric(3, 2), nullable=True))
    op.add_column("product_marketplace_listings", sa.Column("review_count", sa.Integer(), nullable=True))

    op.create_table(
        "business_expenses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expense_type", sa.Enum(*EXPENSE_TYPES, name="business_expense_type"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="BDT", nullable=False),
        sa.Column("incurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_status", sa.Enum("PAID", "DUE", name="business_expense_status"), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("counterparty", sa.String(length=160), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=40), server_default="MANUAL", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_business_expenses_amount_nonnegative"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_expenses_seller_incurred_at", "business_expenses", ["seller_id", "incurred_at"])
    op.create_index("ix_business_expenses_seller_status", "business_expenses", ["seller_id", "payment_status"])

    op.create_table(
        "marketplace_store_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marketplace", sa.String(length=120), nullable=False),
        sa.Column("seller_rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("rating_count", sa.Integer(), nullable=True),
        sa.Column("positive_rating_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("ship_on_time_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("chat_response_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=40), server_default="MANUAL", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_marketplace_store_metrics_seller_captured_at", "marketplace_store_metrics", ["seller_id", "captured_at"])


def downgrade() -> None:
    op.drop_index("ix_marketplace_store_metrics_seller_captured_at", table_name="marketplace_store_metrics")
    op.drop_table("marketplace_store_metrics")
    op.drop_index("ix_business_expenses_seller_status", table_name="business_expenses")
    op.drop_index("ix_business_expenses_seller_incurred_at", table_name="business_expenses")
    op.drop_table("business_expenses")
    sa.Enum(name="business_expense_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="business_expense_type").drop(op.get_bind(), checkfirst=True)
    op.drop_column("product_marketplace_listings", "review_count")
    op.drop_column("product_marketplace_listings", "rating")
    op.drop_column("sales_records", "delivery_district")
    op.drop_column("sales_records", "customer_reference")
