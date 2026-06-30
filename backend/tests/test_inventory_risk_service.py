from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.core.config import settings
from app.models.inventory_risk import InventoryRiskDataStatus, InventoryRiskLevel
from app.models.reorder_recommendation import ReorderRecommendationAction, ReorderRecommendationStatus
from app.models.stockout_prediction import StockoutPredictionStatus
from app.services.inventory_risk_service import InventoryRiskService


class FakeInventoryRiskRepository:
    def __init__(self) -> None:
        self.products = []
        self.stockouts = {}
        self.reorders = {}
        self.rows = {}

    def iter_product_batches(self, *, batch_size, seller_id=None, product_id=None):
        filtered = [
            row for row in self.products
            if (seller_id is None or row[0].seller_id == seller_id)
            and (product_id is None or row[0].id == product_id)
        ]
        for index in range(0, len(filtered), batch_size):
            yield filtered[index:index + batch_size]

    def latest_stockout_for_products(self, *, seller_id, product_ids, as_of_date):
        return {pid: row for pid, row in self.stockouts.items() if pid in product_ids and row.seller_id == seller_id}

    def latest_reorder_for_products(self, *, seller_id, product_ids, as_of_date):
        return {pid: row for pid, row in self.reorders.items() if pid in product_ids and row.seller_id == seller_id}

    def add_idempotent(self, assessment):
        key = (assessment.product_id, assessment.as_of_date, assessment.calculation_version)
        existing = self.rows.get(key)
        if existing:
            return existing, False
        self.rows[key] = assessment
        return assessment, True

    def latest(self, *, seller_id, product_id, calculation_version):
        rows = [
            row for row in self.rows.values()
            if row.seller_id == seller_id and row.product_id == product_id
            and (calculation_version is None or row.calculation_version == calculation_version)
        ]
        return sorted(rows, key=lambda row: (row.as_of_date, row.assessed_at), reverse=True)[0] if rows else None

    def history(self, *, seller_id, product_id, from_date, to_date, calculation_version, order, limit, offset):
        rows = [
            row for row in self.rows.values()
            if row.seller_id == seller_id and row.product_id == product_id
            and (from_date is None or row.as_of_date >= from_date)
            and (to_date is None or row.as_of_date <= to_date)
            and (calculation_version is None or row.calculation_version == calculation_version)
        ]
        rows.sort(key=lambda row: row.as_of_date, reverse=order == "desc")
        return rows[offset:offset + limit], len(rows)

    def list_current(self, *, seller_id, risk_level, product_id, category, from_date, to_date, open_reorder_required, limit, offset):
        rows = [
            row for row in self.rows.values()
            if row.seller_id == seller_id
            and (risk_level is None or row.risk_level == risk_level)
            and (product_id is None or row.product_id == product_id)
            and (from_date is None or row.as_of_date >= from_date)
            and (to_date is None or row.as_of_date <= to_date)
        ]
        rows.sort(key=lambda row: row.assessed_at, reverse=True)
        return rows[offset:offset + limit], len(rows)


def seller():
    return SimpleNamespace(id=uuid4())


def product(owner, *, stock=100, lead_time=8, category="General"):
    return SimpleNamespace(id=uuid4(), seller_id=owner.id, stock_quantity=stock, supplier_lead_time=lead_time, category=category)


def stockout(owner, item, *, days, inventory_position, status=StockoutPredictionStatus.PREDICTED, confidence=90, predicted_date=None, snapshot_date="2026-06-29"):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        days_remaining=Decimal(str(days)),
        inventory_position=inventory_position,
        quantity_on_hand=inventory_position,
        prediction_status=status,
        predicted_stockout_date=predicted_date,
        confidence_score=Decimal(str(confidence)),
        calculation_metadata={"inventory_snapshot_date": snapshot_date},
    )


def reorder(owner, item, *, lead=8, safety=3, review=7, deadline=None, action=ReorderRecommendationAction.HOLD, status=ReorderRecommendationStatus.OPEN, confidence=90):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        supplier_lead_time_days=lead,
        safety_buffer_days=safety,
        review_period_days=review,
        reorder_deadline=deadline,
        action=action,
        recommendation_status=status,
        confidence_score=Decimal(str(confidence)),
    )


class InventoryRiskServiceTests(unittest.TestCase):
    def test_already_out_of_stock_is_critical(self):
        owner = seller()
        item = product(owner, stock=0)
        service = InventoryRiskService(repository=FakeInventoryRiskRepository())

        assessment = service.build_assessment(
            product=item,
            seller=owner,
            stockout_prediction=stockout(owner, item, days=0, inventory_position=0, status=StockoutPredictionStatus.ALREADY_OUT_OF_STOCK),
            reorder_recommendation=reorder(owner, item),
            as_of_date=date(2026, 6, 29),
            assessed_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
            calculation_version="v1",
        )

        self.assertEqual(InventoryRiskLevel.CRITICAL, assessment.risk_level)
        self.assertGreaterEqual(assessment.risk_score, 85)

    def test_stockout_before_supplier_delivery_is_critical(self):
        owner = seller()
        item = product(owner)
        service = InventoryRiskService(repository=FakeInventoryRiskRepository())

        assessment = service.build_assessment(
            product=item,
            seller=owner,
            stockout_prediction=stockout(owner, item, days=6, inventory_position=60, predicted_date=date(2026, 7, 2)),
            reorder_recommendation=reorder(owner, item, lead=8, safety=3),
            as_of_date=date(2026, 6, 29),
            assessed_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
            calculation_version="v1",
        )

        self.assertEqual(InventoryRiskLevel.CRITICAL, assessment.risk_level)

    def test_coverage_equal_to_required_is_high(self):
        owner = seller()
        item = product(owner)
        service = InventoryRiskService(repository=FakeInventoryRiskRepository())

        assessment = service.build_assessment(
            product=item,
            seller=owner,
            stockout_prediction=stockout(owner, item, days=11, inventory_position=110),
            reorder_recommendation=reorder(owner, item, lead=8, safety=3),
            as_of_date=date(2026, 6, 29),
            assessed_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
            calculation_version="v1",
        )

        self.assertEqual(InventoryRiskLevel.HIGH, assessment.risk_level)

    def test_medium_and_low_risk(self):
        owner = seller()
        item = product(owner)
        service = InventoryRiskService(repository=FakeInventoryRiskRepository())
        medium = service.build_assessment(
            product=item,
            seller=owner,
            stockout_prediction=stockout(owner, item, days=15, inventory_position=150),
            reorder_recommendation=reorder(owner, item, lead=8, safety=3, review=7),
            as_of_date=date(2026, 6, 29),
            assessed_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
            calculation_version="v1",
        )
        low = service.build_assessment(
            product=item,
            seller=owner,
            stockout_prediction=stockout(owner, item, days=30, inventory_position=300),
            reorder_recommendation=reorder(owner, item, lead=8, safety=3, review=7),
            as_of_date=date(2026, 6, 29),
            assessed_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
            calculation_version="v2",
        )

        self.assertEqual(InventoryRiskLevel.MEDIUM, medium.risk_level)
        self.assertEqual(InventoryRiskLevel.LOW, low.risk_level)

    def test_insufficient_sales_data_has_no_low_level(self):
        owner = seller()
        item = product(owner)
        service = InventoryRiskService(repository=FakeInventoryRiskRepository())

        assessment = service.build_assessment(
            product=item,
            seller=owner,
            stockout_prediction=stockout(owner, item, days=0, inventory_position=100, status=StockoutPredictionStatus.INSUFFICIENT_DATA),
            reorder_recommendation=reorder(owner, item),
            as_of_date=date(2026, 6, 29),
            assessed_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
            calculation_version="v1",
        )

        self.assertEqual(InventoryRiskDataStatus.INSUFFICIENT, assessment.data_status)
        self.assertIsNone(assessment.risk_level)
        self.assertEqual(Decimal("50.00"), assessment.risk_score)

    def test_missing_lead_time_uses_default_not_low_by_missing_prediction(self):
        owner = seller()
        item = product(owner, lead_time=None)
        service = InventoryRiskService(repository=FakeInventoryRiskRepository())

        assessment = service.build_assessment(
            product=item,
            seller=owner,
            stockout_prediction=None,
            reorder_recommendation=None,
            as_of_date=date(2026, 6, 29),
            assessed_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
            calculation_version="v1",
        )

        self.assertEqual(InventoryRiskDataStatus.INSUFFICIENT, assessment.data_status)
        self.assertIsNone(assessment.risk_level)

    def test_stale_inventory_snapshot_is_limited(self):
        owner = seller()
        item = product(owner)
        service = InventoryRiskService(repository=FakeInventoryRiskRepository())

        assessment = service.build_assessment(
            product=item,
            seller=owner,
            stockout_prediction=stockout(owner, item, days=30, inventory_position=300, snapshot_date="2026-06-20"),
            reorder_recommendation=reorder(owner, item),
            as_of_date=date(2026, 6, 29),
            assessed_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
            calculation_version="v1",
        )

        self.assertEqual(InventoryRiskDataStatus.LIMITED, assessment.data_status)
        self.assertLessEqual(assessment.confidence_score, 70)

    def test_score_boundaries_and_configurable_thresholds(self):
        owner = seller()
        item = product(owner)
        original_gap = settings.inventory_risk_significant_coverage_gap_days
        settings.inventory_risk_significant_coverage_gap_days = 10.0
        try:
            service = InventoryRiskService(repository=FakeInventoryRiskRepository())
            assessment = service.build_assessment(
                product=item,
                seller=owner,
                stockout_prediction=stockout(owner, item, days=10, inventory_position=100),
                reorder_recommendation=reorder(owner, item, lead=8, safety=3, deadline=date(2026, 6, 29)),
                as_of_date=date(2026, 6, 29),
                assessed_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
                calculation_version="v1",
            )
        finally:
            settings.inventory_risk_significant_coverage_gap_days = original_gap

        self.assertGreaterEqual(assessment.risk_score, 0)
        self.assertLessEqual(assessment.risk_score, 100)
        self.assertEqual(InventoryRiskLevel.HIGH, assessment.risk_level)

    def test_formula_versioning_duplicate_retry_and_seller_isolation(self):
        first_seller = seller()
        second_seller = seller()
        item = product(first_seller)
        repo = FakeInventoryRiskRepository()
        repo.products = [(item, first_seller)]
        repo.stockouts[item.id] = stockout(first_seller, item, days=4, inventory_position=40)
        repo.reorders[item.id] = reorder(first_seller, item, deadline=date(2026, 6, 29), action=ReorderRecommendationAction.REORDER)
        service = InventoryRiskService(repository=repo)

        first = service.assess_for_batch(as_of_date=date(2026, 6, 29), calculation_version="v1")
        duplicate = service.assess_for_batch(as_of_date=date(2026, 6, 29), calculation_version="v1")
        new_version = service.assess_for_batch(as_of_date=date(2026, 6, 29), calculation_version="v2")
        visible = service.latest_risk(seller_id=first_seller.id, product_id=item.id)
        leaked = service.latest_risk(seller_id=second_seller.id, product_id=item.id)

        self.assertEqual(1, first.created_count)
        self.assertEqual(0, duplicate.created_count)
        self.assertEqual(1, duplicate.skipped_count)
        self.assertEqual(1, new_version.created_count)
        self.assertIsNotNone(visible)
        self.assertIsNone(leaked)


if __name__ == "__main__":
    unittest.main()
