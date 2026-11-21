from __future__ import annotations

import unittest
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
import importlib.util

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.product import Product, ProductMarketplaceListing, ProductMarketplaceListingStatus, ProductStatus
from app.models.sales_record import SalesRecord, SalesRecordStatus
from app.models.seller import Seller
from app.services.copilot.sales_revenue_analytics_service import SalesRevenueAnalyticsService
from app.services.copilot.tool_registry import SqlAlchemyCopilotToolDataAccess


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


class ProductMarketplaceListingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(
            self.engine,
            tables=[
                Seller.__table__,
                Product.__table__,
                ProductMarketplaceListing.__table__,
                SalesRecord.__table__,
            ],
        )
        self.db = Session(self.engine)
        self.seller = Seller(email="seller@example.com", password_hash="hash")
        self.other_seller = Seller(email="other@example.com", password_hash="hash")
        self.db.add_all([self.seller, self.other_seller])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(
            self.engine,
            tables=[
                SalesRecord.__table__,
                ProductMarketplaceListing.__table__,
                Product.__table__,
                Seller.__table__,
            ],
        )
        self.engine.dispose()

    def test_product_can_have_sku_status_default_and_updated_at(self) -> None:
        product = self._product(title="Alpha", sku="SKU-1")
        self.db.add(product)
        self.db.commit()
        self.db.refresh(product)

        self.assertEqual("SKU-1", product.sku)
        self.assertEqual(ProductStatus.ACTIVE, product.status)
        self.assertIsNotNone(product.updated_at)
        original_updated_at = product.updated_at
        product.title = "Alpha updated"
        product.updated_at = datetime(2026, 7, 6, tzinfo=timezone.utc)
        self.db.commit()
        self.db.refresh(product)
        self.assertNotEqual(original_updated_at, product.updated_at)

    def test_migration_upgrade_and_downgrade_declare_required_columns(self) -> None:
        migration = _load_listing_migration_module()
        source = Path(migration.__file__).read_text()

        self.assertEqual("a8b9c0d1e2f3", migration.revision)
        self.assertEqual("f7a8b9c0d1e2", migration.down_revision)
        self.assertIn("op.add_column(\"products\", sa.Column(\"sku\"", source)
        self.assertIn("op.add_column(\n            \"products\"", source)
        self.assertIn("product_marketplace_listings", source)
        self.assertIn("op.drop_table(\"product_marketplace_listings\")", source)
        self.assertIn("op.drop_column(\"products\", column_name)", source)
        self.assertIn("uq_product_marketplace_listings_seller_marketplace_external_id", source)

    def test_product_can_have_marketplace_listing(self) -> None:
        product = self._product(title="Alpha", sku="SKU-1")
        self.db.add(product)
        self.db.flush()
        listing = ProductMarketplaceListing(
            seller_id=self.seller.id,
            product_id=product.id,
            marketplace="Daraz",
            marketplace_listing_id="DRZ-1",
            listing_status=ProductMarketplaceListingStatus.ACTIVE,
            currency="BDT",
            selling_price=Decimal("120.00"),
            is_primary=True,
        )
        self.db.add(listing)
        self.db.commit()
        self.db.refresh(product)

        self.assertEqual(1, len(product.marketplace_listings))
        self.assertEqual("Daraz", product.marketplace_listings[0].marketplace)

    def test_marketplace_listing_seller_isolation(self) -> None:
        own_product = self._product(title="Own", sku="OWN")
        other_product = self._product(title="Other", sku="OTHER", seller=self.other_seller)
        self.db.add_all([own_product, other_product])
        self.db.flush()
        self.db.add_all(
            [
                self._listing(own_product, marketplace="Daraz"),
                self._listing(other_product, marketplace="Daraz", seller=self.other_seller),
            ]
        )
        self.db.commit()

        data = _ListingTestDataAccess(self.db)
        payload, _ = data.list_products(
            seller_id=self.seller.id,
            filters={"marketplace": "Daraz"},
            sort_by="created_at_desc",
            limit=10,
            offset=0,
        )

        self.assertEqual(1, payload["pagination"]["total"])
        self.assertEqual(str(own_product.id), payload["products"][0]["id"])

    def test_list_and_count_products_filtered_by_marketplace(self) -> None:
        daraz_product = self._product(title="Daraz item", sku="D1")
        shopify_product = self._product(title="Shopify item", sku="S1")
        missing_product = self._product(title="Missing listing", sku="M1")
        self.db.add_all([daraz_product, shopify_product, missing_product])
        self.db.flush()
        self.db.add_all(
            [
                self._listing(daraz_product, marketplace="Daraz"),
                self._listing(shopify_product, marketplace="Shopify"),
            ]
        )
        self.db.commit()

        data = _ListingTestDataAccess(self.db)
        count, _ = data.count_products(seller_id=self.seller.id, filters={"marketplace": "Daraz"})
        listed, _ = data.list_products(
            seller_id=self.seller.id,
            filters={"marketplace": "Daraz"},
            sort_by="created_at_desc",
            limit=10,
            offset=0,
        )

        self.assertEqual(1, count["count"])
        self.assertEqual(["Daraz item"], [item["title"] for item in listed["products"]])
        self.assertEqual("Daraz", listed["products"][0]["marketplace"])

    def test_listed_filter_reports_account_total_when_no_listings_exist(self) -> None:
        # Regression: "koyta product listed ache?" with 2 products and no listing rows was answered "0 products".
        self.db.add_all([self._product(title="Shoe", sku="A1"), self._product(title="Sandal", sku="A2")])
        self.db.add(self._product(title="Other seller item", sku="O1", seller=self.other_seller))
        self.db.commit()

        data = _ListingTestDataAccess(self.db)
        count, _ = data.count_products(seller_id=self.seller.id, filters={"listed": True})
        listed, _ = data.list_products(seller_id=self.seller.id, filters={"listed": True}, sort_by="created_at_desc", limit=10, offset=0)
        unfiltered, _ = data.count_products(seller_id=self.seller.id, filters={})

        expected = {"total_products_in_account": 2, "products_with_active_marketplace_listing": 0}
        self.assertEqual(0, count["count"])
        self.assertLessEqual(expected.items(), count["listing_summary"].items())
        self.assertLessEqual(expected.items(), listed["listing_summary"].items())
        self.assertNotIn("listing_summary", unfiltered)

    def test_product_profile_includes_listing_data(self) -> None:
        product = self._product(title="Alpha", sku="SKU-1")
        self.db.add(product)
        self.db.flush()
        self.db.add(self._listing(product, marketplace="Daraz", currency="BDT", price=Decimal("99.00")))
        self.db.commit()

        payload, _ = _ListingTestDataAccess(self.db).get_product_profile(
            seller_id=self.seller.id,
            product_id=product.id,
        )

        self.assertEqual("Daraz", payload["product"]["marketplace"])
        self.assertEqual("BDT", payload["product"]["currency"])
        self.assertEqual(1, len(payload["product"]["marketplace_listings"]))

    def test_revenue_summary_filters_sales_by_marketplace_listing(self) -> None:
        daraz_product = self._product(title="Daraz item", sku="D1")
        shopify_product = self._product(title="Shopify item", sku="S1")
        self.db.add_all([daraz_product, shopify_product])
        self.db.flush()
        self.db.add_all(
            [
                self._listing(daraz_product, marketplace="Daraz", price=Decimal("100.00")),
                self._listing(shopify_product, marketplace="Shopify", price=Decimal("100.00")),
                self._sale(daraz_product, source_reference="sale-1"),
                self._sale(shopify_product, source_reference="sale-2"),
            ]
        )
        self.db.commit()

        payload, missing = SalesRevenueAnalyticsService(self.db).get_revenue_summary(
            seller_id=self.seller.id,
            from_date=datetime(2026, 7, 1, tzinfo=timezone.utc).date(),
            to_date=datetime(2026, 7, 31, tzinfo=timezone.utc).date(),
            marketplace="Daraz",
            compare_to_previous_period=False,
        )

        self.assertEqual(Decimal("100.00"), payload["gross_revenue"])
        self.assertEqual(1, payload["order_count"])
        self.assertNotIn("marketplace filter could not be applied", " ".join(missing))

    def test_missing_marketplace_reported_without_fake_marketplace(self) -> None:
        product = self._product(title="Alpha", sku="SKU-1")
        self.db.add(product)
        self.db.commit()

        payload, missing = _ListingTestDataAccess(self.db).get_product_profile(
            seller_id=self.seller.id,
            product_id=product.id,
        )

        self.assertIsNone(payload["product"]["marketplace"])
        self.assertIn("MISSING_MARKETPLACE", payload["product"]["missing_setup_data"])
        self.assertIn("MISSING_MARKETPLACE", " ".join(missing))

    def _product(self, *, title: str, sku: str, seller: Seller | None = None) -> Product:
        return Product(
            seller_id=(seller or self.seller).id,
            title=title,
            sku=sku,
            description="A test product description.",
            category="Test",
            specifications={},
            searchable_text=title,
            cost_price=Decimal("50.00"),
            selling_price=Decimal("100.00"),
            stock_quantity=5,
            supplier_lead_time=3,
            minimum_margin=Decimal("10.00"),
        )

    def _listing(
        self,
        product: Product,
        *,
        marketplace: str,
        seller: Seller | None = None,
        currency: str = "BDT",
        price: Decimal = Decimal("100.00"),
    ) -> ProductMarketplaceListing:
        return ProductMarketplaceListing(
            seller_id=(seller or self.seller).id,
            product_id=product.id,
            marketplace=marketplace,
            marketplace_listing_id=f"{marketplace}-{product.id}",
            listing_status=ProductMarketplaceListingStatus.ACTIVE,
            currency=currency,
            selling_price=price,
            is_primary=True,
        )

    def _sale(self, product: Product, *, source_reference: str) -> SalesRecord:
        return SalesRecord(
            seller_id=self.seller.id,
            product_id=product.id,
            source_reference=source_reference,
            status=SalesRecordStatus.COMPLETED,
            sold_at=datetime(2026, 7, 6, tzinfo=timezone.utc),
            quantity_sold=1,
            returned_units=0,
            refunded_restocked_units=0,
            is_test_order=False,
        )


class _ListingTestDataAccess(SqlAlchemyCopilotToolDataAccess):
    def _product_ids_with_fee_policy(self, *, seller_id, product_ids):
        return set()

    def _product_ids_with_pricing_policy(self, *, seller_id, product_ids):
        return set()

    def _product_ids_with_sales(self, *, seller_id, product_ids):
        return set()

    def _latest_row(self, model, *, seller_id, product_id, order_column):
        return None

    def _count_rows(self, statement):
        return 0

    def _has_fee_policy(self, *, seller_id, product_id, category):
        return False

    def _has_pricing_policy(self, *, seller_id, product_id):
        return False

    def _revenue_total(self, *, seller_id, product_id, from_date, to_date):
        return Decimal("0.00")


def _load_listing_migration_module():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "a8b9c0d1e2f3_add_product_marketplace_listings.py"
    )
    spec = importlib.util.spec_from_file_location("product_marketplace_listing_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
