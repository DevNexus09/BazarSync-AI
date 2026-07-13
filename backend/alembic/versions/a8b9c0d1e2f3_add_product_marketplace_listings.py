"""add product marketplace listings

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-07-06 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


PRODUCT_STATUS_VALUES = ("ACTIVE", "INACTIVE", "DRAFT", "ARCHIVED", "DISCONTINUED")
LISTING_STATUS_VALUES = ("ACTIVE", "INACTIVE", "DRAFT", "OUT_OF_STOCK", "ARCHIVED", "UNKNOWN")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if dialect == "postgresql":
        enum_names = {enum["name"] for enum in inspector.get_enums()}
        if "product_status" not in enum_names:
            postgresql.ENUM(*PRODUCT_STATUS_VALUES, name="product_status").create(bind, checkfirst=True)
        if "product_marketplace_listing_status" not in enum_names:
            postgresql.ENUM(*LISTING_STATUS_VALUES, name="product_marketplace_listing_status").create(bind, checkfirst=True)

    product_columns = {column["name"] for column in inspector.get_columns("products")}
    if "sku" not in product_columns:
        op.add_column("products", sa.Column("sku", sa.String(length=120), nullable=True))
    if "status" not in product_columns:
        op.add_column(
            "products",
            sa.Column(
                "status",
                _enum("product_status", PRODUCT_STATUS_VALUES, dialect),
                nullable=False,
                server_default="ACTIVE",
            ),
        )
    if "updated_at" not in product_columns:
        op.add_column(
            "products",
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )

    indexes = {index["name"] for index in inspector.get_indexes("products")}
    constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("products")}
    if "ix_products_status" not in indexes:
        op.create_index("ix_products_status", "products", ["status"])
    if "uq_products_seller_sku" not in constraints:
        op.create_unique_constraint("uq_products_seller_sku", "products", ["seller_id", "sku"])
    if "uq_products_id_seller_id" not in constraints:
        op.create_unique_constraint("uq_products_id_seller_id", "products", ["id", "seller_id"])

    table_names = set(sa.inspect(bind).get_table_names())
    if "product_marketplace_listings" not in table_names:
        op.create_table(
            "product_marketplace_listings",
            sa.Column("id", postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(length=36), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(length=36), nullable=False),
            sa.Column("marketplace", sa.String(length=120), nullable=False),
            sa.Column("marketplace_listing_id", sa.String(length=255), nullable=True),
            sa.Column("listing_url", sa.Text(), nullable=True),
            sa.Column("listing_status", _enum("product_marketplace_listing_status", LISTING_STATUS_VALUES, dialect), nullable=False, server_default="UNKNOWN"),
            sa.Column("currency", sa.String(length=3), nullable=True),
            sa.Column("selling_price", sa.Numeric(12, 2), nullable=True),
            sa.Column("previous_selling_price", sa.Numeric(12, 2), nullable=True),
            sa.Column("category_on_marketplace", sa.String(length=160), nullable=True),
            sa.Column("title_on_marketplace", sa.String(length=255), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false") if dialect == "postgresql" else sa.text("0")),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("selling_price IS NULL OR selling_price >= 0", name="ck_product_marketplace_listings_selling_price_nonnegative"),
            sa.CheckConstraint("previous_selling_price IS NULL OR previous_selling_price >= 0", name="ck_product_marketplace_listings_previous_price_nonnegative"),
            sa.CheckConstraint("selling_price IS NULL OR currency IS NOT NULL", name="ck_product_marketplace_listings_currency_when_price"),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id", "seller_id"], ["products.id", "products.seller_id"], ondelete="CASCADE", name="fk_product_marketplace_listings_product_seller"),
            sa.UniqueConstraint("seller_id", "marketplace", "marketplace_listing_id", name="uq_product_marketplace_listings_seller_marketplace_external_id"),
        )
        op.create_index("ix_product_marketplace_listings_seller_id", "product_marketplace_listings", ["seller_id"])
        op.create_index("ix_product_marketplace_listings_product_id", "product_marketplace_listings", ["product_id"])
        op.create_index("ix_product_marketplace_listings_marketplace", "product_marketplace_listings", ["marketplace"])
        op.create_index("ix_product_marketplace_listings_listing_status", "product_marketplace_listings", ["listing_status"])
        op.create_index("ix_product_marketplace_listings_seller_marketplace_status", "product_marketplace_listings", ["seller_id", "marketplace", "listing_status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if "product_marketplace_listings" in inspector.get_table_names():
        op.drop_index("ix_product_marketplace_listings_seller_marketplace_status", table_name="product_marketplace_listings")
        op.drop_index("ix_product_marketplace_listings_listing_status", table_name="product_marketplace_listings")
        op.drop_index("ix_product_marketplace_listings_marketplace", table_name="product_marketplace_listings")
        op.drop_index("ix_product_marketplace_listings_product_id", table_name="product_marketplace_listings")
        op.drop_index("ix_product_marketplace_listings_seller_id", table_name="product_marketplace_listings")
        op.drop_table("product_marketplace_listings")

    product_columns = {column["name"] for column in sa.inspect(bind).get_columns("products")}
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("products")}
    constraints = {constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("products")}
    if "uq_products_seller_sku" in constraints:
        op.drop_constraint("uq_products_seller_sku", "products", type_="unique")
    if "uq_products_id_seller_id" in constraints:
        op.drop_constraint("uq_products_id_seller_id", "products", type_="unique")
    if "ix_products_status" in indexes:
        op.drop_index("ix_products_status", table_name="products")
    for column_name in ("updated_at", "status", "sku"):
        if column_name in product_columns:
            op.drop_column("products", column_name)

    if dialect == "postgresql":
        postgresql.ENUM(name="product_marketplace_listing_status").drop(bind, checkfirst=True)
        postgresql.ENUM(name="product_status").drop(bind, checkfirst=True)


def _enum(name: str, values: tuple[str, ...], dialect: str):
    if dialect == "postgresql":
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)
