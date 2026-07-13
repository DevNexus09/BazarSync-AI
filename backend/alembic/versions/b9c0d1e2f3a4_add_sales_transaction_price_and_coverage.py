"""add sales transaction price and coverage

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-07-06 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


PRICE_SOURCE_VALUES = ("TRANSACTION", "IMPORTED_TRANSACTION", "CURRENT_PRODUCT_PRICE_ESTIMATE", "UNKNOWN")
COVERAGE_STATUS_VALUES = ("COMPLETE", "PARTIAL", "UNKNOWN", "FAILED")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if dialect == "postgresql":
        enum_names = {enum["name"] for enum in inspector.get_enums()}
        if "sales_record_price_source" not in enum_names:
            postgresql.ENUM(*PRICE_SOURCE_VALUES, name="sales_record_price_source").create(bind, checkfirst=True)
        if "sales_data_completeness_status" not in enum_names:
            postgresql.ENUM(*COVERAGE_STATUS_VALUES, name="sales_data_completeness_status").create(bind, checkfirst=True)

    sales_columns = {column["name"] for column in inspector.get_columns("sales_records")}
    if "unit_price" not in sales_columns:
        op.add_column("sales_records", sa.Column("unit_price", sa.Numeric(12, 2), nullable=True))
    if "line_total" not in sales_columns:
        op.add_column("sales_records", sa.Column("line_total", sa.Numeric(14, 2), nullable=True))
    if "currency" not in sales_columns:
        op.add_column("sales_records", sa.Column("currency", sa.String(length=3), nullable=True))
    if "marketplace_listing_id" not in sales_columns:
        op.add_column("sales_records", sa.Column("marketplace_listing_id", sa.String(length=255), nullable=True))
    if "price_source" not in sales_columns:
        op.add_column(
            "sales_records",
            sa.Column(
                "price_source",
                _enum("sales_record_price_source", PRICE_SOURCE_VALUES, dialect),
                nullable=False,
                server_default="UNKNOWN",
            ),
        )

    if "source_reference" in sales_columns:
        op.alter_column("sales_records", "source_reference", existing_type=sa.String(length=255), nullable=True)

    indexes = {index["name"] for index in inspector.get_indexes("sales_records")}
    if "ix_sales_records_marketplace_listing_id" not in indexes:
        op.create_index("ix_sales_records_marketplace_listing_id", "sales_records", ["marketplace_listing_id"])

    if dialect != "sqlite":
        checks = {constraint["name"] for constraint in inspector.get_check_constraints("sales_records")}
        if "ck_sales_records_quantity_sold_nonnegative" in checks:
            op.drop_constraint("ck_sales_records_quantity_sold_nonnegative", "sales_records", type_="check")
        if "ck_sales_records_quantity_sold_positive" not in checks:
            op.create_check_constraint("ck_sales_records_quantity_sold_positive", "sales_records", "quantity_sold > 0")
        if "ck_sales_records_unit_price_nonnegative" not in checks:
            op.create_check_constraint("ck_sales_records_unit_price_nonnegative", "sales_records", "unit_price IS NULL OR unit_price >= 0")
        if "ck_sales_records_line_total_nonnegative" not in checks:
            op.create_check_constraint("ck_sales_records_line_total_nonnegative", "sales_records", "line_total IS NULL OR line_total >= 0")
        if "ck_sales_records_currency_length" not in checks:
            op.create_check_constraint("ck_sales_records_currency_length", "sales_records", "unit_price IS NULL OR currency IS NULL OR length(currency) = 3")

    if "sales_data_coverage" not in inspector.get_table_names():
        op.create_table(
            "sales_data_coverage",
            sa.Column("id", postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(length=36), nullable=False),
            sa.Column("marketplace", sa.String(length=120), nullable=True),
            sa.Column("product_id", postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(length=36), nullable=True),
            sa.Column("source", sa.String(length=120), nullable=False),
            sa.Column("coverage_start_date", sa.Date(), nullable=False),
            sa.Column("coverage_end_date", sa.Date(), nullable=False),
            sa.Column("completeness_status", _enum("sales_data_completeness_status", COVERAGE_STATUS_VALUES, dialect), nullable=False, server_default="UNKNOWN"),
            sa.Column("imported_record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("valid_sales_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("invalid_or_excluded_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_imported_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint("coverage_end_date >= coverage_start_date", name="ck_sales_data_coverage_date_order"),
            sa.CheckConstraint("imported_record_count >= 0", name="ck_sales_data_coverage_imported_nonnegative"),
            sa.CheckConstraint("valid_sales_count >= 0", name="ck_sales_data_coverage_valid_nonnegative"),
            sa.CheckConstraint("invalid_or_excluded_count >= 0", name="ck_sales_data_coverage_invalid_nonnegative"),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_sales_data_coverage_seller_dates", "sales_data_coverage", ["seller_id", "coverage_start_date", "coverage_end_date"])
        op.create_index("ix_sales_data_coverage_product_id", "sales_data_coverage", ["product_id"])
        op.create_index("ix_sales_data_coverage_marketplace", "sales_data_coverage", ["marketplace"])
        op.create_index("ix_sales_data_coverage_seller_marketplace_status", "sales_data_coverage", ["seller_id", "marketplace", "completeness_status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if "sales_data_coverage" in inspector.get_table_names():
        op.drop_index("ix_sales_data_coverage_seller_marketplace_status", table_name="sales_data_coverage")
        op.drop_index("ix_sales_data_coverage_marketplace", table_name="sales_data_coverage")
        op.drop_index("ix_sales_data_coverage_product_id", table_name="sales_data_coverage")
        op.drop_index("ix_sales_data_coverage_seller_dates", table_name="sales_data_coverage")
        op.drop_table("sales_data_coverage")

    sales_columns = {column["name"] for column in inspector.get_columns("sales_records")}
    indexes = {index["name"] for index in inspector.get_indexes("sales_records")}
    if "ix_sales_records_marketplace_listing_id" in indexes:
        op.drop_index("ix_sales_records_marketplace_listing_id", table_name="sales_records")

    if dialect != "sqlite":
        checks = {constraint["name"] for constraint in inspector.get_check_constraints("sales_records")}
        for name in ("ck_sales_records_unit_price_nonnegative", "ck_sales_records_line_total_nonnegative", "ck_sales_records_currency_length"):
            if name in checks:
                op.drop_constraint(name, "sales_records", type_="check")
        if "ck_sales_records_quantity_sold_positive" in checks:
            op.drop_constraint("ck_sales_records_quantity_sold_positive", "sales_records", type_="check")
        if "ck_sales_records_quantity_sold_nonnegative" not in checks:
            op.create_check_constraint("ck_sales_records_quantity_sold_nonnegative", "sales_records", "quantity_sold >= 0")

    for column_name in ("price_source", "marketplace_listing_id", "currency", "line_total", "unit_price"):
        if column_name in sales_columns:
            op.drop_column("sales_records", column_name)

    if "source_reference" in sales_columns:
        op.alter_column("sales_records", "source_reference", existing_type=sa.String(length=255), nullable=False)

    if dialect == "postgresql":
        postgresql.ENUM(name="sales_data_completeness_status").drop(bind, checkfirst=True)
        postgresql.ENUM(name="sales_record_price_source").drop(bind, checkfirst=True)


def _enum(name: str, values: tuple[str, ...], dialect: str):
    if dialect == "postgresql":
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)
