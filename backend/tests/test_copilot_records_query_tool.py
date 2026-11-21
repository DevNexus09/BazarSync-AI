from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.inventory_stock_in import InventoryStockIn
from app.models.product import Product
from app.models.sales_record import SalesRecord, SalesRecordPriceSource, SalesRecordStatus
from app.models.seller import Seller
from app.services.copilot.tool_registry import CopilotToolContext, CopilotToolRegistry, ToolExecutionStatus


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


TABLES = [Seller.__table__, Product.__table__, SalesRecord.__table__, InventoryStockIn.__table__]


class RecordsQueryToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.db = Session(self.engine)
        self.seller = Seller(email="seller@example.com", password_hash="hash")
        self.other = Seller(email="other@example.com", password_hash="hash")
        self.db.add_all([self.seller, self.other])
        self.db.flush()
        self.shoe = self._product("Lex Loafer", self.seller, category="Men's Footwear")
        self.sandal = self._product("Nipun Sandal", self.seller, category="Women's Footwear")
        self.foreign = self._product("Other Shoe", self.other, category="Men's Footwear")
        self.db.add_all([self.shoe, self.sandal, self.foreign])
        self.db.flush()
        # 2026-11-01 18:30 UTC is 2026-11-02 00:30 in Dhaka, so it belongs to the 2nd.
        self.db.add_all(
            [
                self._sale(self.shoe, "2026-11-01T04:00:00", 2, Decimal("1874.00")),
                self._sale(self.sandal, "2026-11-01T10:00:00", 1, Decimal("247.10")),
                self._sale(self.shoe, "2026-11-01T18:30:00", 1, Decimal("1874.00")),
                self._sale(self.shoe, "2026-11-02T08:00:00", 1, Decimal("1874.00"), status=SalesRecordStatus.CANCELLED),
                self._sale(self.foreign, "2026-11-01T05:00:00", 5, Decimal("9999.00")),
                InventoryStockIn(seller_id=self.seller.id, product_id=self.sandal.id, quantity=60, received_at=_utc("2026-11-12T03:00:00"), unit_cost=Decimal("140.79"), currency="BDT"),
                InventoryStockIn(seller_id=self.other.id, product_id=self.foreign.id, quantity=999, received_at=_utc("2026-11-12T03:00:00"), unit_cost=Decimal("1.00"), currency="BDT"),
            ]
        )
        self.db.commit()
        self.registry = CopilotToolRegistry()
        self.context = CopilotToolContext(seller_id=self.seller.id, db=self.db)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine, tables=list(reversed(TABLES)))
        self.engine.dispose()

    def _run(self, **arguments):
        return self.registry.execute(name="query_business_records", context=self.context, arguments=arguments)

    def test_tool_is_registered_read_only(self):
        tool = self.registry.get_tool("query_business_records")
        self.assertTrue(tool.allowed_in_read_only_mode)
        self.assertNotIn("seller_id", tool.argument_schema.model_fields)

    def test_sum_revenue_by_day_matches_sales_records(self):
        # 2026-11-01: 2 x 1874.00 + 247.10 = 3995.10. The 18:30 UTC sale is 00:30 on the 2nd in Dhaka. The CANCELLED sale is excluded.
        result = self._run(entity="sales", aggregate="sum", measure="revenue", group_by="day", from_date="2026-11-01", to_date="2026-11-02", sort="asc")

        self.assertEqual(ToolExecutionStatus.SUCCEEDED, result.status, result.error)
        self.assertEqual(
            [{"period": "2026-11-01", "value": "3995.10", "row_count": 2}, {"period": "2026-11-02", "value": "1874.00", "row_count": 1}],
            result.data["rows"],
        )
        self.assertEqual(("money", "BDT", "sales_records", "records_query_v1"), (result.data["measure_unit"], result.data["currency"], result.data["source"], result.data["calculation_version"]))
        self.assertEqual(3, result.data["row_count"])

    def test_category_filter_is_case_insensitive_and_group_by_product(self):
        result = self._run(entity="sales", aggregate="sum", measure="units", group_by="product", category="men's footwear", from_date="2026-11-01", to_date="2026-11-30")

        self.assertEqual(1, len(result.data["rows"]))
        self.assertEqual("Lex Loafer", result.data["rows"][0]["product"]["title"])
        self.assertEqual("3", result.data["rows"][0]["value"])

    def test_other_seller_rows_excluded(self):
        sales = self._run(entity="sales", aggregate="count")
        stock = self._run(entity="stock_ins", aggregate="sum", measure="quantity")
        listed = self._run(entity="sales", aggregate="list", limit=200)

        self.assertEqual(3, sales.data["rows"][0]["value"])
        self.assertEqual("60", stock.data["rows"][0]["value"])
        self.assertNotIn(str(self.foreign.id), str(listed.data))

    def test_other_seller_product_id_is_blocked(self):
        result = self._run(entity="sales", aggregate="count", product_id=str(self.foreign.id))
        self.assertEqual(ToolExecutionStatus.BLOCKED, result.status)
        self.assertEqual("PRODUCT_ACCESS_DENIED", result.error["code"])
        self.assertEqual({}, {key: value for key, value in result.data.items() if key == "rows"})

    def test_unknown_measure_rejected_as_invalid_arguments(self):
        for arguments in (
            {"entity": "sales", "aggregate": "sum", "measure": "profit; drop table"},
            {"entity": "sales", "aggregate": "sum"},
            {"entity": "alerts", "aggregate": "avg", "measure": "price"},
            {"entity": "sales", "marketplace": "Daraz"},
            {"entity": "sales", "seller_id": str(self.other.id)},
            {"entity": "invoices"},
        ):
            with self.subTest(arguments=arguments):
                result = self._run(**arguments)
                self.assertEqual(ToolExecutionStatus.BLOCKED, result.status)
                self.assertEqual("INVALID_ARGUMENTS", result.error["code"])

    def test_empty_range_returns_observed_zero_with_row_count_0(self):
        total = self._run(entity="sales", aggregate="sum", measure="revenue", from_date="2026-01-01", to_date="2026-01-31")
        average = self._run(entity="sales", aggregate="avg", measure="revenue", from_date="2026-01-01", to_date="2026-01-31")

        self.assertEqual(ToolExecutionStatus.SUCCEEDED, total.status)
        self.assertEqual(0, total.data["row_count"])
        self.assertEqual([{"value": "0", "row_count": 0}], total.data["rows"])
        self.assertTrue(any(item.startswith("NO_MATCHING_RECORDS") for item in total.data["missing_data"]))
        # No observations means no average: unavailable, not zero.
        self.assertIsNone(average.data["rows"][0]["value"])

    def test_missing_cost_is_unavailable_not_zero(self):
        self.db.add(InventoryStockIn(seller_id=self.seller.id, product_id=self.shoe.id, quantity=5, received_at=_utc("2026-11-13T03:00:00"), unit_cost=None, currency=None))
        self.db.commit()

        result = self._run(entity="stock_ins", aggregate="sum", measure="total_cost", product_id=str(self.shoe.id))

        self.assertIsNone(result.data["rows"][0]["value"])
        self.assertTrue(any(item.startswith("MEASURE_UNAVAILABLE") for item in result.data["missing_data"]))

    def test_limit_truncation_flagged(self):
        listed = self._run(entity="sales", aggregate="list", limit=2)
        grouped = self._run(entity="sales", aggregate="count", group_by="day", limit=1)

        self.assertEqual(2, len(listed.data["rows"]))
        self.assertTrue(listed.data["truncated"])
        self.assertEqual(3, listed.data["row_count"])
        self.assertEqual("sales_records", listed.data["rows"][0]["evidence"]["source_table"])
        self.assertTrue(grouped.data["truncated"])
        self.assertFalse(self._run(entity="sales", aggregate="list", limit=50).data["truncated"])

    def test_stock_in_list_has_cost_and_product(self):
        result = self._run(entity="stock_ins", from_date="2026-11-08", to_date="2026-11-14")

        row = result.data["rows"][0]
        self.assertEqual((60, "140.79", "BDT", "8447.40"), (row["quantity"], row["unit_cost"], row["currency"], row["total_cost"]))
        self.assertEqual("Nipun Sandal", row["product"]["title"])

    def _product(self, title: str, seller: Seller, *, category: str) -> Product:
        return Product(seller_id=seller.id, title=title, sku=f"sku-{uuid4().hex[:6]}", category=category, cost_price=Decimal("60.00"), selling_price=Decimal("100.00"), stock_quantity=5, supplier_lead_time=7, minimum_margin=Decimal("10.00"))

    def _sale(self, product: Product, sold_at: str, quantity: int, unit_price: Decimal, *, status=SalesRecordStatus.COMPLETED) -> SalesRecord:
        return SalesRecord(
            seller_id=product.seller_id,
            product_id=product.id,
            status=status,
            sold_at=_utc(sold_at),
            quantity_sold=quantity,
            unit_price=unit_price,
            line_total=unit_price * quantity,
            currency="BDT",
            price_source=SalesRecordPriceSource.TRANSACTION,
            returned_units=0,
            refunded_restocked_units=0,
            is_test_order=False,
        )


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


if __name__ == "__main__":
    unittest.main()
