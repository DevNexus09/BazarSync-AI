from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import UUID, uuid4

from app.models.sales_record import SalesRecordStatus
from app.services.copilot.profit_margin_analytics_service import ProfitMarginAnalyticsService
from app.services.copilot.sales_revenue_analytics_service import (
    SalesLine,
    SalesRevenueAnalyticsService,
    is_valid_sales_record,
)


SELLER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _product(*, cost_price=Decimal("40.00"), selling_price=Decimal("120.00"), category="cat"):
    return SimpleNamespace(id=uuid4(), title="Product A", category=category, cost_price=cost_price, selling_price=selling_price)


def _sale(product, *, status=SalesRecordStatus.COMPLETED, unit_price=None, quantity=1, returned=0, test_order=False):
    sale = SimpleNamespace(
        id=uuid4(),
        seller_id=SELLER_ID,
        product_id=product.id,
        product=product,
        status=status,
        sold_at=datetime(2026, 7, 1, 10, tzinfo=timezone.utc),
        quantity_sold=quantity,
        returned_units=returned,
        refunded_restocked_units=0,
        is_test_order=test_order,
    )
    if unit_price is not None:
        sale.unit_price = unit_price
    return sale


def _line(product, *, unit_price=Decimal("100.00"), quantity=1, returned=0, estimated=False):
    sale = _sale(product, unit_price=unit_price, quantity=quantity, returned=returned)
    net_units = max(0, quantity - returned)
    return SalesLine(sale=sale, product=product, gross_units=quantity, net_units=net_units, unit_price=unit_price, revenue_is_estimated=estimated)


class _FakeRevenueService(SalesRevenueAnalyticsService):
    def __init__(self, lines_by_period):
        self._lines_by_period = lines_by_period

    def _sales_lines(self, *, seller_id, from_date, to_date, product_id=None, category=None):
        return list(self._lines_by_period.get((from_date, to_date), []))


def _fee_policy(product=None, category=None):
    return SimpleNamespace(
        product_id=getattr(product, "id", None),
        category=category,
        percentage_commission_rate=Decimal("0.100000"),
        payment_fee_rate=Decimal("0.020000"),
        fixed_per_unit_fee=Decimal("1.00"),
        fixed_per_order_fee=Decimal("2.00"),
        fulfilment_fee=Decimal("3.00"),
        other_variable_cost=Decimal("0.50"),
        shipping_subsidy=Decimal("0.00"),
    )


class CopilotFinancialAnalyticsTests(unittest.TestCase):
    def test_revenue_summary_uses_transaction_prices_when_available(self):
        product = _product(selling_price=Decimal("999.00"))
        current = (date(2026, 7, 1), date(2026, 7, 1))
        service = _FakeRevenueService({current: [_line(product, unit_price=Decimal("25.00"), quantity=2)]})

        payload, missing = service.get_revenue_summary(seller_id=SELLER_ID, from_date=current[0], to_date=current[1], compare_to_previous_period=False)

        self.assertEqual(Decimal("50.00"), payload["gross_revenue"])
        self.assertFalse(payload["revenue_is_estimated"])
        self.assertFalse([note for note in missing if "estimated from current Product.selling_price" in note])

    def test_revenue_summary_does_not_use_current_price_when_transaction_price_exists(self):
        product = _product(selling_price=Decimal("999.00"))
        current = (date(2026, 7, 1), date(2026, 7, 1))
        service = _FakeRevenueService({current: [_line(product, unit_price=Decimal("10.00"), quantity=3)]})

        payload, _ = service.get_revenue_summary(seller_id=SELLER_ID, from_date=current[0], to_date=current[1], compare_to_previous_period=False)

        self.assertEqual(Decimal("30.00"), payload["gross_revenue"])

    def test_valid_sales_statuses_counted_and_invalid_statuses_excluded(self):
        product = _product()

        self.assertTrue(is_valid_sales_record(_sale(product, status=SalesRecordStatus.COMPLETED)))
        self.assertTrue(is_valid_sales_record(_sale(product, status=SalesRecordStatus.FULFILLED)))
        self.assertFalse(is_valid_sales_record(_sale(product, status=SalesRecordStatus.PENDING)))
        self.assertFalse(is_valid_sales_record(_sale(product, status=SalesRecordStatus.CANCELLED)))
        self.assertFalse(is_valid_sales_record(_sale(product, status=SalesRecordStatus.FAILED_PAYMENT)))
        self.assertFalse(is_valid_sales_record(_sale(product, status=SalesRecordStatus.COMPLETED, test_order=True)))

    def test_previous_period_comparison_is_calculated_deterministically(self):
        product = _product()
        current = (date(2026, 7, 2), date(2026, 7, 2))
        previous = (date(2026, 7, 1), date(2026, 7, 1))
        service = _FakeRevenueService(
            {
                current: [_line(product, unit_price=Decimal("100.00"), quantity=2)],
                previous: [_line(product, unit_price=Decimal("50.00"), quantity=1)],
            }
        )

        payload, _ = service.get_revenue_summary(seller_id=SELLER_ID, from_date=current[0], to_date=current[1])

        self.assertEqual(Decimal("200.00"), payload["gross_revenue"])
        self.assertEqual(Decimal("50.00"), payload["previous_period_revenue"])
        self.assertEqual(Decimal("150.00"), payload["revenue_change"])
        self.assertEqual(Decimal("300.00"), payload["percentage_change"])

    def test_profit_excludes_missing_cost_and_fee_policy(self):
        product_without_cost = _product(cost_price=None)
        product_without_fee = _product(category="no-fee")
        current = (date(2026, 7, 1), date(2026, 7, 1))
        service = ProfitMarginAnalyticsService.__new__(ProfitMarginAnalyticsService)
        service._sales = _FakeRevenueService(
            {
                current: [
                    _line(product_without_cost, unit_price=Decimal("100.00"), quantity=1),
                    _line(product_without_fee, unit_price=Decimal("100.00"), quantity=1),
                ]
            }
        )
        service._fee_policies = lambda seller_id: [_fee_policy(category="fee-covered")]

        payload, missing = service.get_profit_summary(seller_id=SELLER_ID, from_date=current[0], to_date=current[1])

        self.assertEqual("PARTIAL", payload["profit_label"])
        self.assertIsNone(payload["estimated_profit"])
        self.assertEqual(1, len(payload["products_excluded_due_to_missing_cost"]))
        self.assertEqual(1, len(payload["products_excluded_due_to_missing_marketplace_fee_policy"]))
        self.assertIn("Some products were excluded from profit because product cost is missing.", missing)
        self.assertIn("Some products were excluded from profit because marketplace fee policy is missing.", missing)

    def test_partial_profit_label_when_some_products_excluded(self):
        calculable = _product(category="cat")
        missing_cost = _product(cost_price=None, category="cat")
        current = (date(2026, 7, 1), date(2026, 7, 1))
        service = ProfitMarginAnalyticsService.__new__(ProfitMarginAnalyticsService)
        service._sales = _FakeRevenueService(
            {
                current: [
                    _line(calculable, unit_price=Decimal("100.00"), quantity=1),
                    _line(missing_cost, unit_price=Decimal("100.00"), quantity=1),
                ]
            }
        )
        service._fee_policies = lambda seller_id: [_fee_policy(category="cat")]

        payload, _ = service.get_profit_summary(seller_id=SELLER_ID, from_date=current[0], to_date=current[1])

        self.assertEqual("PARTIAL", payload["profit_label"])
        self.assertEqual(1, len(payload["profit_by_product"]))
        self.assertEqual(Decimal("41.50"), payload["estimated_profit"])

    def test_no_sales_returns_zero_without_fake_revenue(self):
        current = (date(2026, 7, 1), date(2026, 7, 1))
        service = _FakeRevenueService({current: []})

        payload, missing = service.get_revenue_summary(seller_id=SELLER_ID, from_date=current[0], to_date=current[1], compare_to_previous_period=False)

        self.assertEqual(Decimal("0"), payload["gross_revenue"])
        self.assertEqual(0, payload["units_sold"])
        self.assertIn("No completed/fulfilled non-test sales records were found for the requested scope.", missing)


if __name__ == "__main__":
    unittest.main()
