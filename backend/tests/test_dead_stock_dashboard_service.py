from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.models.dead_stock_assessment import DeadStockClassification, DeadStockDataStatus, DeadStockRiskLevel
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.services.dead_stock_dashboard_service import DeadStockDashboardService


class FakeRepo:
    def __init__(self, rows):
        self._rows = rows

    def rows(self, **kwargs):
        rows = self._rows
        if kwargs.get("classification"):
            rows = [row for row in rows if row["assessment"].classification == kwargs["classification"]]
        if kwargs.get("risk_level"):
            rows = [row for row in rows if row["assessment"].risk_level == kwargs["risk_level"]]
        if kwargs.get("recommendation_action"):
            rows = [row for row in rows if row["recommendation"].primary_action == kwargs["recommendation_action"]]
        return rows, len(rows)

    def product_bundle(self, *, seller_id, product_id):
        return next((row for row in self._rows if row["product"].seller_id == seller_id and row["product"].id == product_id), None)

    def product_exists(self, *, seller_id, product_id):
        return any(row["product"].seller_id == seller_id and row["product"].id == product_id for row in self._rows)


def row(*, classification=DeadStockClassification.DEAD_STOCK, risk=DeadStockRiskLevel.CRITICAL, currency="BDT", duration=14):
    seller_id = uuid4()
    product_id = uuid4()
    now = datetime(2026, 7, 3, 10, tzinfo=timezone.utc)
    return {
        "product": SimpleNamespace(id=product_id, seller_id=seller_id, title="Dead Lotion", category="Beauty", stock_quantity=10),
        "assessment": SimpleNamespace(
            id=uuid4(),
            classification=classification,
            risk_level=risk,
            risk_score=Decimal("88.00"),
            eligible_quantity=8,
            inventory_age_days=92,
            inventory_age_is_estimated=True,
            days_since_last_sale=64,
            data_status=DeadStockDataStatus.LIMITED,
            assessed_at=now,
            calculation_version="risk_v1",
            triggered_rules=["NO_VALID_SALES"],
            rule_results={},
            visibility_status="VISIBILITY_DATA_UNAVAILABLE",
            inventory_age_state="AGE_ESTIMATED",
        ),
        "recommendation": SimpleNamespace(
            id=uuid4(),
            primary_action=DeadStockRecoveryAction.DISCOUNT,
            recommendation_status="OPEN",
            recommended_discount_rate=Decimal("0.10"),
            recommended_price=Decimal("285.00"),
            confidence_score=Decimal("70.00"),
            generated_at=now,
            calculation_version="recovery_v1",
            secondary_actions=[],
            explanation="Discount recommended.",
            evidence={},
            rejected_actions=[],
        ),
        "capital": SimpleNamespace(
            locked_capital=Decimal("1600.00"),
            gross_recovered_cash=Decimal("1200.00"),
            gross_recovered_cash_low=Decimal("900.00"),
            gross_recovered_cash_high=Decimal("1400.00"),
            confidence_score=Decimal("58.00"),
            calculated_at=now,
            calculation_version="capital_v1",
            evidence={"currency": currency, "duration_days": duration},
            estimate_status=SimpleNamespace(value="HEURISTIC"),
            estimation_method=SimpleNamespace(value="CONSERVATIVE_HEURISTIC"),
            contribution_recovered=Decimal("-20.00"),
            capital_recovery_ratio=Decimal("0.75"),
        ),
        "aging": SimpleNamespace(age_source=SimpleNamespace(value="FIRST_POSITIVE_SNAPSHOT"), calculated_at=now),
        "velocity": SimpleNamespace(daily_sales_rate=Decimal("0.1000"), data_status=SimpleNamespace(value="SUFFICIENT"), calculated_at=now),
    }


class DeadStockDashboardServiceTests(unittest.TestCase):
    def test_summary_aggregates_only_comparable_money(self):
        first = row()
        second = row(currency="USD")
        service = DeadStockDashboardService(repository=FakeRepo([first, second]))

        summary = service.summary(seller_id=first["product"].seller_id)

        self.assertEqual(2, summary.dead_stock_count)
        self.assertIsNone(summary.total_locked_capital)
        self.assertIsNone(summary.estimated_recoverable_cash)
        self.assertFalse(summary.monetary_totals_comparable)

    def test_products_filter_and_intelligence_payload(self):
        item = row()
        service = DeadStockDashboardService(repository=FakeRepo([item]))

        page = service.products(
            seller_id=item["product"].seller_id,
            classification=DeadStockClassification.DEAD_STOCK,
            risk_level=DeadStockRiskLevel.CRITICAL,
            category=None,
            marketplace=None,
            min_age_days=None,
            min_locked_capital=None,
            recommendation_action=DeadStockRecoveryAction.DISCOUNT,
            data_status=None,
            sort="risk",
            limit=20,
            offset=0,
        )
        intelligence = service.product_intelligence(seller_id=item["product"].seller_id, product_id=item["product"].id)

        self.assertEqual(1, page.total)
        self.assertEqual(Decimal("1600.00"), page.items[0].locked_capital)
        self.assertEqual(DeadStockRecoveryAction.DISCOUNT, intelligence.primary_recovery_recommendation)
        self.assertEqual(["NO_VALID_SALES"], intelligence.triggered_rules)
        self.assertEqual(Decimal("900.00"), intelligence.potential_recovered_cash_low)


if __name__ == "__main__":
    unittest.main()
