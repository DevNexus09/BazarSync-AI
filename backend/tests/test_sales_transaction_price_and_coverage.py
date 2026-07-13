from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.product import Product, ProductMarketplaceListing, ProductMarketplaceListingStatus
from app.models.sales_data_coverage import SalesDataCompletenessStatus, SalesDataCoverage
from app.models.sales_record import SalesRecord, SalesRecordPriceSource, SalesRecordStatus
from app.models.seller import Seller
from app.schemas.sales_import import SalesImportRecord, SalesImportRequest
from app.services.copilot.sales_revenue_analytics_service import SalesRevenueAnalyticsService
from app.services.sales_import_service import SalesImportService


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


class SalesTransactionPriceAndCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(
            self.engine,
            tables=[
                Seller.__table__,
                Product.__table__,
                ProductMarketplaceListing.__table__,
                SalesRecord.__table__,
                SalesDataCoverage.__table__,
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
                SalesDataCoverage.__table__,
                SalesRecord.__table__,
                ProductMarketplaceListing.__table__,
                Product.__table__,
                Seller.__table__,
            ],
        )
        self.engine.dispose()

    def test_migration_upgrade_and_downgrade_declare_required_columns(self) -> None:
        migration = _load_migration_module()
        source = Path(migration.__file__).read_text()

        self.assertEqual("b9c0d1e2f3a4", migration.revision)
        self.assertEqual("a8b9c0d1e2f3", migration.down_revision)
        self.assertIn("op.add_column(\"sales_records\", sa.Column(\"unit_price\"", source)
        self.assertIn("op.add_column(\"sales_records\", sa.Column(\"line_total\"", source)
        self.assertIn("sales_data_coverage", source)
        self.assertIn("op.drop_table(\"sales_data_coverage\")", source)
        self.assertIn("sales_record_price_source", source)

    def test_sales_import_persists_transaction_price_currency_and_line_total(self) -> None:
        product = self._product("Imported")
        self.db.add(product)
        self.db.commit()
        payload = SalesImportRequest(
            records=[
                SalesImportRecord(
                    product_id=product.id,
                    quantity=3,
                    sold_at=datetime(2025, 1, 2, 10, tzinfo=timezone.utc),
                    status=SalesRecordStatus.COMPLETED,
                    unit_price=Decimal("12.50"),
                    currency="BDT",
                    source_reference="order-1",
                )
            ],
            source="csv",
        )

        with patch("app.tasks.dead_stock_workflow_tasks.enqueue_dead_stock_recalculation", return_value=True):
            response = SalesImportService(self.db).import_records(seller_id=self.seller.id, payload=payload)

        sale = self.db.execute(select(SalesRecord).where(SalesRecord.source_reference == "order-1")).scalar_one()
        coverage = self.db.execute(select(SalesDataCoverage).where(SalesDataCoverage.seller_id == self.seller.id)).scalar_one()
        self.assertEqual(1, response.imported_count)
        self.assertEqual(Decimal("12.50"), sale.unit_price)
        self.assertEqual(Decimal("37.50"), sale.line_total)
        self.assertEqual("BDT", sale.currency)
        self.assertEqual(SalesRecordPriceSource.IMPORTED_TRANSACTION, sale.price_source)
        self.assertEqual(SalesDataCompletenessStatus.UNKNOWN, coverage.completeness_status)
        self.assertEqual(1, coverage.valid_sales_count)

    def test_sales_import_skips_duplicate_source_reference_per_seller(self) -> None:
        product = self._product("Duplicate")
        self.db.add(product)
        self.db.commit()
        payload = SalesImportRequest(
            records=[
                SalesImportRecord(product_id=product.id, quantity=1, sold_at=datetime(2025, 1, 2, tzinfo=timezone.utc), status=SalesRecordStatus.COMPLETED, source_reference="dup"),
                SalesImportRecord(product_id=product.id, quantity=1, sold_at=datetime(2025, 1, 3, tzinfo=timezone.utc), status=SalesRecordStatus.COMPLETED, source_reference="dup"),
            ]
        )

        with patch("app.tasks.dead_stock_workflow_tasks.enqueue_dead_stock_recalculation", return_value=True):
            response = SalesImportService(self.db).import_records(seller_id=self.seller.id, payload=payload)

        self.assertEqual(1, response.imported_count)
        self.assertEqual(1, response.skipped_duplicate_count)

    def test_sales_import_rejects_product_from_another_seller(self) -> None:
        other_product = self._product("Other", seller=self.other_seller)
        self.db.add(other_product)
        self.db.commit()
        payload = SalesImportRequest(
            records=[
                SalesImportRecord(product_id=other_product.id, quantity=1, sold_at=datetime(2025, 1, 2, tzinfo=timezone.utc), status=SalesRecordStatus.COMPLETED)
            ]
        )

        with self.assertRaises(ValueError):
            SalesImportService(self.db).import_records(seller_id=self.seller.id, payload=payload)

    def test_revenue_summary_uses_transaction_price_and_labels_estimated_when_missing(self) -> None:
        exact = self._product("Exact", price=Decimal("999.00"))
        legacy = self._product("Legacy", price=Decimal("100.00"))
        self.db.add_all([exact, legacy])
        self.db.flush()
        self.db.add_all(
            [
                self._sale(exact, source_reference="exact", quantity=2, unit_price=Decimal("25.00")),
                self._sale(legacy, source_reference="legacy", quantity=1),
                self._coverage(status=SalesDataCompletenessStatus.COMPLETE),
            ]
        )
        self.db.commit()

        payload, missing = SalesRevenueAnalyticsService(self.db).get_revenue_summary(
            seller_id=self.seller.id,
            from_date=date(2025, 1, 1),
            to_date=date(2025, 1, 31),
            compare_to_previous_period=False,
        )

        self.assertEqual(Decimal("150.00"), payload["gross_revenue"])
        self.assertTrue(payload["revenue_is_estimated"])
        self.assertEqual(SalesRecordPriceSource.CURRENT_PRODUCT_PRICE_ESTIMATE.value, payload["revenue_estimation_method"])
        self.assertEqual("LOW", payload["confidence"])
        self.assertIn("MISSING_TRANSACTION_PRICE", payload["missing_data"])
        self.assertIn("MISSING_TRANSACTION_PRICE", " ".join(missing))

    def test_revenue_summary_counts_only_completed_fulfilled_non_test_sales(self) -> None:
        product = self._product("Statuses")
        self.db.add(product)
        self.db.flush()
        self.db.add_all(
            [
                self._sale(product, source_reference="completed", status=SalesRecordStatus.COMPLETED, unit_price=Decimal("10.00")),
                self._sale(product, source_reference="fulfilled", status=SalesRecordStatus.FULFILLED, unit_price=Decimal("10.00")),
                self._sale(product, source_reference="pending", status=SalesRecordStatus.PENDING, unit_price=Decimal("10.00")),
                self._sale(product, source_reference="cancelled", status=SalesRecordStatus.CANCELLED, unit_price=Decimal("10.00")),
                self._sale(product, source_reference="failed", status=SalesRecordStatus.FAILED_PAYMENT, unit_price=Decimal("10.00")),
                self._sale(product, source_reference="test", status=SalesRecordStatus.COMPLETED, unit_price=Decimal("10.00"), is_test_order=True),
                self._coverage(status=SalesDataCompletenessStatus.COMPLETE),
            ]
        )
        self.db.commit()

        payload, _ = SalesRevenueAnalyticsService(self.db).get_revenue_summary(
            seller_id=self.seller.id,
            from_date=date(2025, 1, 1),
            to_date=date(2025, 1, 31),
            compare_to_previous_period=False,
        )

        self.assertEqual(2, payload["order_count"])
        self.assertEqual(Decimal("20.00"), payload["gross_revenue"])

    def test_complete_coverage_allows_no_sales_claim(self) -> None:
        product = self._product("Covered")
        self.db.add(product)
        self.db.flush()
        self.db.add(self._coverage(status=SalesDataCompletenessStatus.COMPLETE, product=product))
        self.db.commit()

        payload, missing = SalesRevenueAnalyticsService(self.db).get_products_with_no_sales(
            seller_id=self.seller.id,
            since_date=date(2025, 1, 1),
        )

        self.assertEqual("NO_SALES", payload["products"][0]["sales_status"])
        self.assertEqual([], missing)

    def test_unknown_coverage_blocks_no_sales_claim(self) -> None:
        product = self._product("Unknown")
        self.db.add(product)
        self.db.commit()

        payload, missing = SalesRevenueAnalyticsService(self.db).get_products_with_no_sales(
            seller_id=self.seller.id,
            since_date=date(2025, 1, 1),
        )

        self.assertEqual("NO_VALID_IMPORTED_SALES_FOUND", payload["products"][0]["sales_status"])
        self.assertEqual("Sales completeness is unknown or partial.", payload["products"][0]["warning"])
        self.assertIn("Sales completeness is unknown or partial", " ".join(missing))

    def test_product_and_marketplace_coverage_are_seller_scoped(self) -> None:
        own = self._product("Own")
        other = self._product("Other", seller=self.other_seller)
        self.db.add_all([own, other])
        self.db.flush()
        self.db.add_all(
            [
                self._listing(own, marketplace="Daraz"),
                self._coverage(status=SalesDataCompletenessStatus.COMPLETE, product=other, seller=self.other_seller, marketplace="Daraz"),
            ]
        )
        self.db.commit()

        payload, _ = SalesRevenueAnalyticsService(self.db).get_products_with_no_sales(
            seller_id=self.seller.id,
            since_date=date(2025, 1, 1),
            marketplace="Daraz",
        )

        self.assertEqual(1, len(payload["products"]))
        self.assertEqual("NO_VALID_IMPORTED_SALES_FOUND", payload["products"][0]["sales_status"])

        self.db.add(self._coverage(status=SalesDataCompletenessStatus.COMPLETE, product=own, marketplace="Daraz"))
        self.db.commit()
        payload, _ = SalesRevenueAnalyticsService(self.db).get_products_with_no_sales(
            seller_id=self.seller.id,
            since_date=date(2025, 1, 1),
            marketplace="Daraz",
        )
        self.assertEqual("NO_SALES", payload["products"][0]["sales_status"])

    def _product(self, title: str, *, seller: Seller | None = None, price: Decimal = Decimal("100.00")) -> Product:
        return Product(
            seller_id=(seller or self.seller).id,
            title=title,
            sku=title.upper(),
            description="Test product",
            category="Test",
            specifications={},
            searchable_text=title,
            cost_price=Decimal("50.00"),
            selling_price=price,
            stock_quantity=5,
            supplier_lead_time=3,
            minimum_margin=Decimal("10.00"),
        )

    def _listing(self, product: Product, *, marketplace: str) -> ProductMarketplaceListing:
        return ProductMarketplaceListing(
            seller_id=product.seller_id,
            product_id=product.id,
            marketplace=marketplace,
            marketplace_listing_id=f"{marketplace}-{product.id}",
            listing_status=ProductMarketplaceListingStatus.ACTIVE,
            currency="BDT",
            selling_price=Decimal("100.00"),
            is_primary=True,
        )

    def _sale(
        self,
        product: Product,
        *,
        source_reference: str,
        status: SalesRecordStatus = SalesRecordStatus.COMPLETED,
        quantity: int = 1,
        unit_price: Decimal | None = None,
        is_test_order: bool = False,
    ) -> SalesRecord:
        return SalesRecord(
            seller_id=product.seller_id,
            product_id=product.id,
            source_reference=source_reference,
            status=status,
            sold_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
            quantity_sold=quantity,
            unit_price=unit_price,
            line_total=None if unit_price is None else unit_price * Decimal(quantity),
            currency="BDT" if unit_price is not None else None,
            price_source=SalesRecordPriceSource.IMPORTED_TRANSACTION if unit_price is not None else SalesRecordPriceSource.UNKNOWN,
            returned_units=0,
            refunded_restocked_units=0,
            is_test_order=is_test_order,
        )

    def _coverage(
        self,
        *,
        status: SalesDataCompletenessStatus,
        product: Product | None = None,
        seller: Seller | None = None,
        marketplace: str | None = None,
    ) -> SalesDataCoverage:
        return SalesDataCoverage(
            seller_id=(seller or self.seller).id,
            product_id=product.id if product else None,
            marketplace=marketplace,
            source="test",
            coverage_start_date=date(2025, 1, 1),
            coverage_end_date=date(2099, 12, 31),
            completeness_status=status,
            imported_record_count=0,
            valid_sales_count=0,
            invalid_or_excluded_count=0,
            last_imported_at=datetime(2025, 1, 31, tzinfo=timezone.utc),
        )


def _load_migration_module():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "b9c0d1e2f3a4_add_sales_transaction_price_and_coverage.py"
    )
    spec = importlib.util.spec_from_file_location("sales_transaction_price_coverage_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
