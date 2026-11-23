from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.models.inventory_risk import InventoryRiskDataStatus, InventoryRiskLevel
from app.models.reorder_recommendation import ReorderRecommendationAction, ReorderRecommendationStatus
from app.models.sales_velocity import SalesVelocityDataStatus
from app.models.stockout_prediction import StockoutPredictionStatus
from app.services.inventory_intelligence_service import InventoryIntelligenceService, _list_item


class FakeInventoryIntelligenceRepository:
    def __init__(self) -> None:
        self.summary_data = {
            "total_active_products": 3,
            "low_risk_products": 1,
            "medium_risk_products": 1,
            "high_risk_products": 1,
            "critical_risk_products": 0,
            "insufficient_data_products": 1,
            "products_requiring_reorder": 2,
            "products_already_out_of_stock": 1,
            "last_calculation_time": datetime.now(timezone.utc),
        }
        self.bundles = {}
        self.reorder_rows = []
        self.risk_rows = []

    def product_exists(self, *, seller_id, product_id):
        return product_id in self.bundles

    def summary(self, *, seller_id):
        return self.summary_data

    def latest_product_bundle(self, *, seller_id, product_id):
        bundle = self.bundles.get(product_id)
        if bundle and bundle["product"].seller_id == seller_id:
            return bundle
        return None

    def reorder_list(self, *, seller_id, risk_level, deadline_from, deadline_to, product_id, category, sort, limit, offset):
        rows = [
            row for row in self.reorder_rows
            if row["product"].seller_id == seller_id
            and (risk_level is None or row["risk"].risk_level == risk_level)
            and (product_id is None or row["product"].id == product_id)
            and (category is None or row["product"].category == category)
            and (deadline_from is None or row["reorder"].reorder_deadline >= deadline_from)
            and (deadline_to is None or row["reorder"].reorder_deadline <= deadline_to)
        ]
        if sort == "deadline":
            rows.sort(key=lambda row: row["reorder"].reorder_deadline)
        elif sort == "recommended_quantity":
            rows.sort(key=lambda row: row["reorder"].recommended_quantity, reverse=True)
        else:
            rows.sort(key=lambda row: _risk_rank(row["risk"].risk_level), reverse=True)
        return rows[offset:offset + limit], len(rows)

    def risks(self, *, seller_id, risk_level, insufficient_data, product_id, category, limit, offset):
        rows = [
            row for row in self.risk_rows
            if row["product"].seller_id == seller_id
            and (risk_level is None or row["risk"].risk_level == risk_level)
            and (insufficient_data is None or (row["risk"].data_status == InventoryRiskDataStatus.INSUFFICIENT) == insufficient_data)
            and (product_id is None or row["product"].id == product_id)
            and (category is None or row["product"].category == category)
        ]
        return rows[offset:offset + limit], len(rows)

    def latest_risks_for_scope(self, *, seller_id, product_id, as_of_date):
        return []


def product(owner_id, *, title="Dove Body Lotion", category="Personal Care"):
    return SimpleNamespace(id=uuid4(), seller_id=owner_id, title=title, category=category, supplier_lead_time=8)


def inventory(owner_id, product_id):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner_id,
        product_id=product_id,
        snapshot_date=date(2026, 6, 29),
        captured_at=datetime(2026, 6, 29, 1, tzinfo=timezone.utc),
        quantity_on_hand=40,
        quantity_reserved=5,
        quantity_available=35,
        quantity_incoming=0,
    )


def velocity(owner_id, product_id):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner_id,
        product_id=product_id,
        as_of_date=date(2026, 6, 29),
        window_days=30,
        daily_sales_rate=Decimal("10.0000"),
        data_status=SalesVelocityDataStatus.SUFFICIENT,
        calculated_at=datetime(2026, 6, 29, 2, tzinfo=timezone.utc),
    )


def prediction(owner_id, product_id, *, days=4, status=StockoutPredictionStatus.PREDICTED):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner_id,
        product_id=product_id,
        days_remaining=Decimal(str(days)),
        predicted_stockout_date=date(2026, 7, 3),
        prediction_status=status,
        calculated_at=datetime(2026, 6, 29, 3, tzinfo=timezone.utc),
    )


def reorder(owner_id, product_id, *, deadline=date(2026, 6, 29), quantity=150):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner_id,
        product_id=product_id,
        action=ReorderRecommendationAction.REORDER,
        recommendation_status=ReorderRecommendationStatus.OPEN,
        recommended_quantity=quantity,
        reorder_deadline=deadline,
        supplier_lead_time_days=8,
        safety_buffer_days=3,
        explanation="Reorder before projected coverage gap.",
        generated_at=datetime(2026, 6, 29, 4, tzinfo=timezone.utc),
    )


def risk(owner_id, product_id, *, level=InventoryRiskLevel.HIGH, status=InventoryRiskDataStatus.SUFFICIENT):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner_id,
        product_id=product_id,
        risk_level=level,
        risk_score=Decimal("75.00"),
        data_status=status,
        confidence_score=Decimal("88.00"),
        calculation_version="v1",
        as_of_date=date(2026, 6, 29),
        assessed_at=datetime(2026, 6, 29, 5, tzinfo=timezone.utc),
        factors={"coverage_gap_days": "7"},
    )


class InventoryIntelligenceServiceTests(unittest.TestCase):
    def test_summary_counts_and_freshness(self):
        repo = FakeInventoryIntelligenceRepository()
        service = InventoryIntelligenceService(repository=repo)

        summary = service.summary(seller_id=uuid4())

        self.assertEqual(3, summary.total_active_products)
        self.assertEqual(1, summary.high_risk_products)
        self.assertEqual(2, summary.products_requiring_reorder)
        self.assertEqual("FRESH", summary.data_freshness_status)

    def test_product_intelligence_missing_data_uses_nulls(self):
        repo = FakeInventoryIntelligenceRepository()
        owner_id = uuid4()
        item = product(owner_id)
        repo.bundles[item.id] = {
            "product": item,
            "inventory": None,
            "velocity": None,
            "prediction": None,
            "reorder": None,
            "risk": None,
        }

        response = InventoryIntelligenceService(repository=repo).product_intelligence(
            seller_id=owner_id,
            product_id=item.id,
        )

        self.assertIsNotNone(response)
        self.assertIsNone(response.daily_sales_rate)
        self.assertIsNone(response.days_remaining)
        self.assertIsNone(response.inventory_risk_score)

    def test_product_intelligence_composes_latest_records(self):
        repo = FakeInventoryIntelligenceRepository()
        owner_id = uuid4()
        item = product(owner_id)
        repo.bundles[item.id] = {
            "product": item,
            "inventory": inventory(owner_id, item.id),
            "velocity": velocity(owner_id, item.id),
            "prediction": prediction(owner_id, item.id),
            "reorder": reorder(owner_id, item.id),
            "risk": risk(owner_id, item.id),
        }

        response = InventoryIntelligenceService(repository=repo).product_intelligence(
            seller_id=owner_id,
            product_id=item.id,
        )

        self.assertEqual(Decimal("10.0000"), response.daily_sales_rate)
        self.assertEqual(Decimal("4"), response.days_remaining)
        self.assertEqual(InventoryRiskLevel.HIGH, response.risk_level)
        self.assertEqual(ReorderRecommendationAction.REORDER, response.reorder_action)
        self.assertEqual(datetime(2026, 6, 29, 5, tzinfo=timezone.utc), response.last_updated_at)
        self.assertEqual(repo.bundles[item.id]["reorder"].id, response.reorder_recommendation_id)
        self.assertEqual(ReorderRecommendationStatus.OPEN, response.recommendation_status)

    def test_reorder_sorting_pagination_and_filtering(self):
        repo = FakeInventoryIntelligenceRepository()
        owner_id = uuid4()
        first = product(owner_id, title="A")
        second = product(owner_id, title="B")
        third = product(owner_id, title="C", category="Other")
        repo.reorder_rows = [
            {"product": first, "risk": risk(owner_id, first.id, level=InventoryRiskLevel.HIGH), "reorder": reorder(owner_id, first.id, deadline=date(2026, 7, 3), quantity=50), "prediction": prediction(owner_id, first.id)},
            {"product": second, "risk": risk(owner_id, second.id, level=InventoryRiskLevel.CRITICAL), "reorder": reorder(owner_id, second.id, deadline=date(2026, 6, 30), quantity=200), "prediction": prediction(owner_id, second.id)},
            {"product": third, "risk": risk(owner_id, third.id, level=InventoryRiskLevel.MEDIUM), "reorder": reorder(owner_id, third.id, deadline=date(2026, 7, 1), quantity=100), "prediction": prediction(owner_id, third.id)},
        ]

        items, total = InventoryIntelligenceService(repository=repo).reorder_list(
            seller_id=owner_id,
            risk_level=None,
            deadline_from=None,
            deadline_to=None,
            product_id=None,
            category="Personal Care",
            sort="deadline",
            limit=1,
            offset=0,
        )

        self.assertEqual(2, total)
        self.assertEqual("B", items[0].product_name)
        self.assertEqual(repo.reorder_rows[1]["reorder"].id, items[0].reorder_recommendation_id)
        self.assertEqual(8, items[0].supplier_lead_time_days)
        # Older rows have no lead-time evidence: unknown, not "not defaulted".
        self.assertIsNone(items[0].supplier_lead_time_defaulted)

    def test_list_item_reports_defaulted_lead_time_and_missing_reorder(self):
        owner_id = uuid4()
        item = product(owner_id)
        defaulted = reorder(owner_id, item.id)
        defaulted.evidence = {"supplier_lead_time_defaulted": True}
        with_reorder = _list_item({"product": item, "risk": risk(owner_id, item.id), "reorder": defaulted, "prediction": None})
        without = _list_item({"product": item, "risk": risk(owner_id, item.id), "reorder": None, "prediction": None})

        self.assertTrue(with_reorder.supplier_lead_time_defaulted)
        self.assertIsNone(without.reorder_recommendation_id)
        self.assertIsNone(without.supplier_lead_time_days)
        self.assertIsNone(without.supplier_lead_time_defaulted)

    def test_risk_filtering_and_seller_isolation(self):
        repo = FakeInventoryIntelligenceRepository()
        owner_id = uuid4()
        other_id = uuid4()
        owned = product(owner_id)
        other = product(other_id)
        repo.risk_rows = [
            {"product": owned, "risk": risk(owner_id, owned.id, level=InventoryRiskLevel.CRITICAL), "reorder": reorder(owner_id, owned.id), "prediction": prediction(owner_id, owned.id)},
            {"product": other, "risk": risk(other_id, other.id, level=InventoryRiskLevel.CRITICAL), "reorder": reorder(other_id, other.id), "prediction": prediction(other_id, other.id)},
            {"product": product(owner_id), "risk": risk(owner_id, uuid4(), status=InventoryRiskDataStatus.INSUFFICIENT), "reorder": None, "prediction": None},
        ]

        items, total = InventoryIntelligenceService(repository=repo).risks(
            seller_id=owner_id,
            risk_level=InventoryRiskLevel.CRITICAL,
            insufficient_data=None,
            product_id=None,
            category=None,
            limit=20,
            offset=0,
        )

        self.assertEqual(1, total)
        self.assertEqual(InventoryRiskLevel.CRITICAL, items[0].risk_level)


def _risk_rank(level):
    return {
        InventoryRiskLevel.CRITICAL: 4,
        InventoryRiskLevel.HIGH: 3,
        InventoryRiskLevel.MEDIUM: 2,
        InventoryRiskLevel.LOW: 1,
    }.get(level, 0)


if __name__ == "__main__":
    unittest.main()
