from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.product import Product, ProductMarketplaceListing
from app.models.sales_data_coverage import SalesDataCompletenessStatus, SalesDataCoverage
from app.models.sales_record import SalesRecord, SalesRecordPriceSource, SalesRecordStatus
from app.models.seller import Seller
from app.services.copilot.metric_execution_service import MetricExecutionService
from app.services.copilot.query_constraints import CatalogValidationError
from app.services.copilot.tool_registry import CopilotToolContext, CopilotToolRegistry, ToolExecutionStatus


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


class MetricExecutionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(
            self.engine,
            tables=[
                Seller.__table__,
                Product.__table__,
                ProductMarketplaceListing.__table__,
                MarketplaceFeePolicy.__table__,
                SalesRecord.__table__,
                SalesDataCoverage.__table__,
            ],
        )
        self.db = Session(self.engine)
        self.seller = Seller(email="seller@example.com", password_hash="hash")
        self.other_seller = Seller(email="other@example.com", password_hash="hash")
        self.db.add_all([self.seller, self.other_seller])
        self.db.commit()
        self.service = MetricExecutionService(self.db)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(
            self.engine,
            tables=[
                SalesDataCoverage.__table__,
                SalesRecord.__table__,
                MarketplaceFeePolicy.__table__,
                ProductMarketplaceListing.__table__,
                Product.__table__,
                Seller.__table__,
            ],
        )
        self.engine.dispose()

    def test_unknown_metric_rejected(self) -> None:
        with self.assertRaisesRegex(CatalogValidationError, "Unknown metric"):
            self.service.execute(seller_id=self.seller.id, metric_key="select * from users")

    def test_unsupported_filter_and_group_by_rejected(self) -> None:
        product = self._product("A")
        self.db.add(product)
        self.db.commit()

        with self.assertRaisesRegex(CatalogValidationError, "Unsupported filter"):
            self.service.execute(seller_id=self.seller.id, metric_key="product_count", filters={"raw_sql": "select 1"})
        with self.assertRaisesRegex(CatalogValidationError, "Unsupported group_by"):
            self.service.execute(seller_id=self.seller.id, metric_key="product_count", group_by=["password"])

    def test_product_ownership_validation_and_seller_isolation(self) -> None:
        own = self._product("Own")
        other = self._product("Other", seller=self.other_seller)
        self.db.add_all([own, other])
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="product_count")

        self.assertEqual(1, result["value"])
        with self.assertRaisesRegex(CatalogValidationError, "product_id does not belong"):
            self.service.execute(seller_id=self.seller.id, metric_key="product_count", filters={"product_id": other.id})

    def test_product_count_exact(self) -> None:
        self.db.add_all([self._product("A"), self._product("B")])
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="product_count")

        self.assertEqual("CALCULATED", result["calculation_status"])
        self.assertEqual(2, result["value"])
        self.assertEqual("products", result["evidence"][0]["source_table"])

    def test_gross_revenue_uses_transaction_price_not_current_selling_price(self) -> None:
        product = self._product("Revenue", price=Decimal("999.00"))
        self.db.add(product)
        self.db.commit()
        self.db.add(self._sale(product, quantity=2, unit_price=Decimal("10.00")))
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="gross_revenue", from_date=date(2025, 1, 1), to_date=date(2025, 1, 31))

        self.assertEqual(Decimal("20.00"), result["value"])
        self.assertEqual("CALCULATED", result["calculation_status"])

    def test_revenue_missing_price_returns_partial(self) -> None:
        product = self._product("Legacy", price=Decimal("999.00"))
        self.db.add(product)
        self.db.commit()
        self.db.add(self._sale(product, quantity=2, unit_price=None))
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="gross_revenue", from_date=date(2025, 1, 1), to_date=date(2025, 1, 31))

        self.assertEqual(Decimal("0"), result["value"])
        self.assertEqual("PARTIAL", result["calculation_status"])
        self.assertIn("MISSING_TRANSACTION_PRICE", result["missing_data"])

    def test_previous_period_revenue_correct(self) -> None:
        product = self._product("Comparison")
        self.db.add(product)
        self.db.commit()
        self.db.add_all(
            [
                self._sale(product, quantity=2, unit_price=Decimal("25.00"), sold_at=datetime(2025, 1, 5, tzinfo=timezone.utc)),
                self._sale(product, quantity=1, unit_price=Decimal("80.00"), sold_at=datetime(2025, 1, 12, tzinfo=timezone.utc)),
            ]
        )
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="previous_period_revenue", from_date=date(2025, 1, 8), to_date=date(2025, 1, 14))

        self.assertEqual("CALCULATED", result["status"])
        self.assertEqual(Decimal("50.00"), result["value"])
        self.assertEqual("2025-01-01", result["comparison"]["period"]["from_date"])
        self.assertEqual("2025-01-07", result["comparison"]["period"]["to_date"])

    def test_revenue_change_correct(self) -> None:
        product = self._product("Change")
        self.db.add(product)
        self.db.commit()
        self.db.add_all(
            [
                self._sale(product, quantity=2, unit_price=Decimal("25.00"), sold_at=datetime(2025, 1, 5, tzinfo=timezone.utc)),
                self._sale(product, quantity=3, unit_price=Decimal("30.00"), sold_at=datetime(2025, 1, 12, tzinfo=timezone.utc)),
            ]
        )
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="revenue_change", from_date=date(2025, 1, 8), to_date=date(2025, 1, 14))

        self.assertEqual(Decimal("40.00"), result["value"])
        self.assertEqual(Decimal("90.00"), result["comparison"]["current_period_revenue"])
        self.assertEqual(Decimal("50.00"), result["comparison"]["previous_period_revenue"])

    def test_revenue_metrics_exclude_invalid_statuses_and_test_orders(self) -> None:
        product = self._product("Valid Only")
        self.db.add(product)
        self.db.commit()
        self.db.add_all(
            [
                self._sale(product, quantity=1, unit_price=Decimal("30.00"), sold_at=datetime(2025, 1, 12, tzinfo=timezone.utc)),
                self._sale(product, quantity=1, unit_price=Decimal("999.00"), sold_at=datetime(2025, 1, 12, tzinfo=timezone.utc), status=SalesRecordStatus.CANCELLED),
                self._sale(product, quantity=1, unit_price=Decimal("888.00"), sold_at=datetime(2025, 1, 12, tzinfo=timezone.utc), status=SalesRecordStatus.PENDING),
                self._sale(product, quantity=1, unit_price=Decimal("777.00"), sold_at=datetime(2025, 1, 12, tzinfo=timezone.utc), status=SalesRecordStatus.FAILED_PAYMENT),
                self._sale(product, quantity=1, unit_price=Decimal("666.00"), sold_at=datetime(2025, 1, 12, tzinfo=timezone.utc), is_test_order=True),
            ]
        )
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="gross_revenue", from_date=date(2025, 1, 8), to_date=date(2025, 1, 14))

        self.assertEqual(Decimal("30.00"), result["value"])

    def test_percentage_revenue_change_handles_zero_denominator(self) -> None:
        product = self._product("Zero Previous")
        self.db.add(product)
        self.db.commit()
        self.db.add(self._sale(product, quantity=3, unit_price=Decimal("30.00"), sold_at=datetime(2025, 1, 12, tzinfo=timezone.utc)))
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="percentage_revenue_change", from_date=date(2025, 1, 8), to_date=date(2025, 1, 14))

        self.assertIsNone(result["value"])
        self.assertEqual("MISSING_DATA", result["status"])
        self.assertIn("PREVIOUS_PERIOD_REVENUE_ZERO", result["missing_data"])

    def test_products_with_revenue_decline_ranking_correct(self) -> None:
        product_a = self._product("A")
        product_b = self._product("B")
        product_c = self._product("C")
        self.db.add_all([product_a, product_b, product_c])
        self.db.commit()
        self.db.add_all(
            [
                self._sale(product_a, quantity=10, unit_price=Decimal("10.00"), sold_at=datetime(2025, 1, 5, tzinfo=timezone.utc)),
                self._sale(product_b, quantity=5, unit_price=Decimal("10.00"), sold_at=datetime(2025, 1, 5, tzinfo=timezone.utc)),
                self._sale(product_c, quantity=2, unit_price=Decimal("10.00"), sold_at=datetime(2025, 1, 5, tzinfo=timezone.utc)),
                self._sale(product_a, quantity=4, unit_price=Decimal("10.00"), sold_at=datetime(2025, 1, 12, tzinfo=timezone.utc)),
                self._sale(product_b, quantity=6, unit_price=Decimal("10.00"), sold_at=datetime(2025, 1, 12, tzinfo=timezone.utc)),
            ]
        )
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="products_with_revenue_decline", from_date=date(2025, 1, 8), to_date=date(2025, 1, 14))

        self.assertEqual(2, result["value"])
        self.assertEqual(str(product_a.id), result["rows"][0]["product_id"])
        self.assertEqual(Decimal("-60.00"), result["rows"][0]["revenue_change"])
        self.assertEqual(str(product_c.id), result["rows"][1]["product_id"])

    def test_average_selling_price_delta_uses_transaction_price(self) -> None:
        product = self._product("ASP", price=Decimal("999.00"))
        self.db.add(product)
        self.db.commit()
        self.db.add_all(
            [
                self._sale(product, quantity=2, unit_price=Decimal("20.00"), sold_at=datetime(2025, 1, 5, tzinfo=timezone.utc)),
                self._sale(product, quantity=2, unit_price=Decimal("30.00"), sold_at=datetime(2025, 1, 12, tzinfo=timezone.utc)),
            ]
        )
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="average_selling_price_delta", from_date=date(2025, 1, 8), to_date=date(2025, 1, 14))

        self.assertEqual(Decimal("10.00"), result["value"])
        self.assertEqual(Decimal("30.00"), result["comparison"]["current_average_selling_price"])
        self.assertEqual(Decimal("20.00"), result["comparison"]["previous_average_selling_price"])

    def test_net_revenue_does_not_fabricate_deductions(self) -> None:
        product = self._product("Net")
        self.db.add(product)
        self.db.commit()
        self.db.add(self._sale(product, quantity=1, unit_price=Decimal("100.00")))
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="net_revenue", from_date=date(2025, 1, 1), to_date=date(2025, 1, 31))

        self.assertEqual("UNSUPPORTED", result["status"])
        self.assertIsNone(result["value"])
        self.assertTrue(any("deductions" in item for item in result["missing_data"]))

    def test_comparison_metrics_keep_seller_isolation(self) -> None:
        own = self._product("Own")
        other = self._product("Other", seller=self.other_seller)
        self.db.add_all([own, other])
        self.db.commit()
        self.db.add_all(
            [
                self._sale(own, quantity=1, unit_price=Decimal("10.00"), sold_at=datetime(2025, 1, 5, tzinfo=timezone.utc)),
                self._sale(own, quantity=1, unit_price=Decimal("30.00"), sold_at=datetime(2025, 1, 12, tzinfo=timezone.utc)),
                self._sale(other, quantity=1, unit_price=Decimal("999.00"), sold_at=datetime(2025, 1, 5, tzinfo=timezone.utc)),
            ]
        )
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="previous_period_revenue", from_date=date(2025, 1, 8), to_date=date(2025, 1, 14))

        self.assertEqual(Decimal("10.00"), result["value"])

    def test_profit_missing_fee_excluded(self) -> None:
        product = self._product("Profit")
        self.db.add(product)
        self.db.commit()
        self.db.add(self._sale(product, quantity=1, unit_price=Decimal("100.00")))
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="estimated_profit", from_date=date(2025, 1, 1), to_date=date(2025, 1, 31))
        excluded = self.service.execute(seller_id=self.seller.id, metric_key="products_excluded_from_profit", from_date=date(2025, 1, 1), to_date=date(2025, 1, 31))

        self.assertEqual("PARTIAL", result["calculation_status"])
        self.assertIn("MISSING_FEE_POLICY", result["missing_data"])
        self.assertEqual(1, excluded["value"])

    def test_no_sales_metric_checks_coverage(self) -> None:
        complete = self._product("Complete")
        unknown = self._product("Unknown")
        self.db.add_all([complete, unknown])
        self.db.commit()
        self.db.add(
            SalesDataCoverage(
                seller_id=self.seller.id,
                product_id=complete.id,
                source="csv",
                coverage_start_date=date(2025, 1, 1),
                coverage_end_date=date(2025, 1, 31),
                completeness_status=SalesDataCompletenessStatus.COMPLETE,
                imported_record_count=0,
                valid_sales_count=0,
                invalid_or_excluded_count=0,
                last_imported_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
            )
        )
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="products_with_no_valid_imported_sales_count", from_date=date(2025, 1, 1), to_date=date(2025, 1, 31))

        self.assertEqual("PARTIAL", result["calculation_status"])
        self.assertEqual(1, result["value"])
        self.assertIn("SALES_COMPLETENESS_UNKNOWN_OR_PARTIAL", result["missing_data"])
        self.assertEqual(str(complete.id), result["rows"][0]["product_id"])

    def test_missing_marketplace_filter_returns_missing_data(self) -> None:
        self.db.add(self._product("A"))
        self.db.commit()

        result = self.service.execute(seller_id=self.seller.id, metric_key="product_count", filters={"marketplace": "Daraz"})

        self.assertEqual("MISSING_DATA", result["calculation_status"])
        self.assertIn("MISSING_MARKETPLACE_DATA", result["missing_data"])

    def test_run_seller_metric_query_tool_works(self) -> None:
        self.db.add(self._product("A"))
        self.db.commit()
        context = CopilotToolContext(seller_id=self.seller.id, db=self.db)

        result = CopilotToolRegistry().execute(
            name="run_seller_metric_query",
            context=context,
            arguments={"metric_key": "product_count", "filters": {}, "limit": 10, "offset": 0},
        )

        self.assertEqual(ToolExecutionStatus.SUCCEEDED, result.status)
        self.assertEqual(1, result.data["value"])
        self.assertEqual("product_count", result.data["metric_key"])

    def _product(self, title: str, *, seller: Seller | None = None, price: Decimal = Decimal("100.00")) -> Product:
        return Product(
            seller_id=(seller or self.seller).id,
            title=title,
            sku=f"sku-{title}",
            category="cat",
            cost_price=Decimal("40.00"),
            selling_price=price,
            stock_quantity=10,
            supplier_lead_time=7,
            minimum_margin=Decimal("10.00"),
        )

    def _sale(
        self,
        product: Product,
        *,
        quantity: int,
        unit_price: Decimal | None,
        sold_at: datetime | None = None,
        status: SalesRecordStatus = SalesRecordStatus.COMPLETED,
        is_test_order: bool = False,
    ) -> SalesRecord:
        return SalesRecord(
            seller_id=product.seller_id,
            product_id=product.id,
            status=status,
            sold_at=sold_at or datetime(2025, 1, 5, tzinfo=timezone.utc),
            quantity_sold=quantity,
            unit_price=unit_price,
            line_total=None if unit_price is None else unit_price * Decimal(quantity),
            currency="BDT" if unit_price is not None else None,
            price_source=SalesRecordPriceSource.IMPORTED_TRANSACTION if unit_price is not None else SalesRecordPriceSource.UNKNOWN,
            is_test_order=is_test_order,
        )


if __name__ == "__main__":
    unittest.main()
