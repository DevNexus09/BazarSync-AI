from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.schemas.dead_stock_readiness import DeadStockReadinessStatus
from app.services.dead_stock_readiness_service import DeadStockReadinessService


class FakeResult:
    def __init__(self, value=None, one_value=None):
        self._value = value
        self._one_value = one_value

    def scalar_one_or_none(self):
        return self._value

    def one(self):
        return self._one_value


class FakeDb:
    def __init__(self, results):
        self._results = list(results)

    def execute(self, statement):
        del statement
        if not self._results:
            raise AssertionError("No fake query result left.")
        return self._results.pop(0)


def _product(*, cost=Decimal("0.00"), price=Decimal("950.00"), stock=25):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=uuid4(),
        title='King Size Premium Bed Sheet 88" x 98"',
        category="Clothing",
        specifications={},
        cost_price=cost,
        selling_price=price,
        stock_quantity=stock,
    )


def _db_for(product, *, total_sales=0, valid_sales=0):
    sales_row = SimpleNamespace(total_records=total_sales, valid_records=valid_sales)
    return FakeDb(
        [
            FakeResult(product),
            FakeResult(None),  # latest aging
            FakeResult(None),  # first stock-in source
            FakeResult(None),  # first positive inventory source
            FakeResult(None),  # latest assessment
            FakeResult(None),  # latest sales velocity
            FakeResult(None),  # latest recommendation
            FakeResult(None),  # latest capital estimate
            FakeResult(None),  # known marketplace from fee
            FakeResult(None),  # known marketplace from pricing policy
            FakeResult(None),  # known currency from pricing policy
            FakeResult(None),  # known currency from fee policy
            FakeResult(None),  # active fee policy
            FakeResult(None),  # active pricing policy
            FakeResult(None),  # latest visibility metric
            FakeResult(one_value=sales_row),
        ]
    )


class DeadStockReadinessServiceTests(unittest.TestCase):
    def test_missing_source_data_returns_blocking_readiness(self):
        product = _product(cost=Decimal("0.00"))
        service = DeadStockReadinessService(_db_for(product))

        readiness = service.evaluate(seller_id=product.seller_id, product_id=product.id)

        self.assertIsNotNone(readiness)
        assert readiness is not None
        self.assertFalse(readiness.ready)
        self.assertEqual(DeadStockReadinessStatus.MISSING, readiness.checks["product_cost"].status)
        self.assertEqual("MISSING_PRODUCT_COST", readiness.checks["product_cost"].reason_code)
        self.assertEqual(DeadStockReadinessStatus.MISSING, readiness.checks["inventory_age_source"].status)
        self.assertEqual("MISSING_INVENTORY_AGE_SOURCE", readiness.checks["inventory_age_source"].reason_code)
        self.assertEqual(DeadStockReadinessStatus.UNAVAILABLE, readiness.checks["visibility_data"].status)
        self.assertFalse(readiness.checks["visibility_data"].blocking)
        self.assertIn("MISSING_PRODUCT_COST", readiness.blocking_reasons)
        self.assertIn("VISIBILITY_DATA_UNAVAILABLE", readiness.non_blocking_reasons)
        self.assertEqual(f"/app/products/{product.id}/edit", readiness.checks["product_cost"].href)

    def test_missing_sales_history_is_not_treated_as_never_sold(self):
        product = _product(cost=Decimal("500.00"))
        service = DeadStockReadinessService(_db_for(product, total_sales=0, valid_sales=0))

        readiness = service.evaluate(seller_id=product.seller_id, product_id=product.id)

        assert readiness is not None
        self.assertEqual("MISSING_SALES_HISTORY", readiness.checks["sales_history"].reason_code)
        self.assertIn("Sales history has not been imported", readiness.checks["sales_history"].message)

    def test_known_sales_history_without_valid_sales_reports_never_sold(self):
        product = _product(cost=Decimal("500.00"))
        service = DeadStockReadinessService(_db_for(product, total_sales=2, valid_sales=0))

        readiness = service.evaluate(seller_id=product.seller_id, product_id=product.id)

        assert readiness is not None
        self.assertEqual("NEVER_SOLD", readiness.checks["sales_history"].reason_code)
        self.assertIn("no completed or fulfilled sales", readiness.checks["sales_history"].message)


if __name__ == "__main__":
    unittest.main()
