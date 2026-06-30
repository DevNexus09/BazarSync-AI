from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.models.reorder_recommendation import ReorderRecommendationAction, ReorderRecommendationStatus
from app.models.sales_velocity import SalesVelocityDataStatus
from app.services.reorder_recommendation_service import (
    ReorderRecommendationNotFoundError,
    ReorderRecommendationService,
)


class FakeReorderRepository:
    def __init__(self) -> None:
        self.products = []
        self.inventory = {}
        self.velocities = {}
        self.stockouts = {}
        self.rows = {}

    def iter_product_batches(self, *, batch_size, seller_id=None, product_id=None):
        filtered = [
            row for row in self.products
            if (seller_id is None or row[0].seller_id == seller_id)
            and (product_id is None or row[0].id == product_id)
        ]
        for index in range(0, len(filtered), batch_size):
            yield filtered[index:index + batch_size]

    def latest_inventory_for_products(self, *, seller_id, product_ids, as_of_date):
        return {pid: item for pid, item in self.inventory.items() if pid in product_ids and item.seller_id == seller_id}

    def latest_velocity_for_products(self, *, seller_id, product_ids, as_of_date):
        return {pid: item for pid, item in self.velocities.items() if pid in product_ids and item.seller_id == seller_id}

    def latest_stockout_for_products(self, *, seller_id, product_ids, as_of_date):
        return {pid: item for pid, item in self.stockouts.items() if pid in product_ids and item.seller_id == seller_id}

    def add_idempotent(self, recommendation):
        key = (recommendation.product_id, recommendation.as_of_date, recommendation.calculation_version)
        existing = self.rows.get(key)
        if existing:
            return existing, False
        self.rows[key] = recommendation
        return recommendation, True

    def latest(self, *, seller_id, product_id, calculation_version):
        rows = [
            row for row in self.rows.values()
            if row.seller_id == seller_id and row.product_id == product_id
            and (calculation_version is None or row.calculation_version == calculation_version)
        ]
        return sorted(rows, key=lambda row: (row.as_of_date, row.generated_at), reverse=True)[0] if rows else None

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

    def get_by_id(self, *, seller_id, recommendation_id):
        for row in self.rows.values():
            if row.seller_id == seller_id and row.id == recommendation_id:
                return row
        return None

    def save_status(self, recommendation):
        return recommendation


def seller():
    return SimpleNamespace(id=uuid4())


def product(owner, *, stock=10, lead_time=8, specs=None):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        stock_quantity=stock,
        supplier_lead_time=lead_time,
        specifications=specs or {},
    )


def inventory(owner, item, *, on_hand, reserved=0):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        quantity_on_hand=on_hand,
        quantity_reserved=reserved,
        quantity_incoming=0,
    )


def velocity(owner, item, *, rate, confidence=90, status=SalesVelocityDataStatus.SUFFICIENT):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        daily_sales_rate=Decimal(str(rate)),
        confidence_score=Decimal(str(confidence)),
        data_status=status,
    )


def stockout(owner, item, *, incoming=0, confidence=85):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        quantity_incoming=incoming,
        confidence_score=Decimal(str(confidence)),
    )


class ReorderRecommendationServiceTests(unittest.TestCase):
    def test_standard_reorder_calculation(self):
        owner = seller()
        item = product(owner, specs={"pack_size": "10"})
        service = ReorderRecommendationService(repository=FakeReorderRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=40),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            stockout_prediction=stockout(owner, item),
            as_of_date=date(2026, 6, 29),
        )

        rec = outcome.recommendation
        self.assertEqual(ReorderRecommendationAction.REORDER, rec.action)
        self.assertEqual(110, rec.reorder_point)
        self.assertEqual(180, rec.target_stock)
        self.assertEqual(140, rec.recommended_quantity)
        self.assertEqual(date(2026, 6, 29), rec.reorder_deadline)

    def test_no_reorder_needed(self):
        owner = seller()
        item = product(owner)
        service = ReorderRecommendationService(repository=FakeReorderRepository())

        rec = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=500),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            stockout_prediction=stockout(owner, item),
            as_of_date=date(2026, 6, 29),
        ).recommendation

        self.assertEqual(ReorderRecommendationAction.HOLD, rec.action)
        self.assertEqual(0, rec.recommended_quantity)
        self.assertEqual(date(2026, 8, 7), rec.reorder_deadline)

    def test_future_reorder_deadline_within_horizon(self):
        owner = seller()
        item = product(owner)
        service = ReorderRecommendationService(repository=FakeReorderRepository())

        rec = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=150),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            stockout_prediction=stockout(owner, item),
            as_of_date=date(2026, 6, 29),
        ).recommendation

        self.assertEqual(ReorderRecommendationAction.REORDER, rec.action)
        self.assertEqual(date(2026, 7, 3), rec.reorder_deadline)

    def test_safety_buffer_and_supplier_lead_time_affect_reorder_point(self):
        owner = seller()
        item = product(owner, lead_time=5, specs={"safety_buffer_days": "2", "review_period_days": "3"})
        service = ReorderRecommendationService(repository=FakeReorderRepository())

        rec = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=20),
            sales_velocity=velocity(owner, item, rate="4.0000"),
            stockout_prediction=stockout(owner, item),
            as_of_date=date(2026, 6, 29),
        ).recommendation

        self.assertEqual(28, rec.reorder_point)
        self.assertEqual(40, rec.target_stock)

    def test_reserved_and_confirmed_incoming_stock(self):
        owner = seller()
        item = product(owner)
        service = ReorderRecommendationService(repository=FakeReorderRepository())

        rec = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=100, reserved=20),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            stockout_prediction=stockout(owner, item, incoming=30),
            as_of_date=date(2026, 6, 29),
        ).recommendation

        self.assertEqual(110, rec.inventory_position)
        self.assertEqual(70, rec.recommended_quantity)

    def test_pack_size_rounding_and_minimum_order_quantity(self):
        owner = seller()
        item = product(owner, specs={"pack_size": "12", "minimum_order_quantity": "50"})
        service = ReorderRecommendationService(repository=FakeReorderRepository())

        rec = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=160),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            stockout_prediction=stockout(owner, item),
            as_of_date=date(2026, 6, 29),
        ).recommendation

        self.assertEqual(50, rec.recommended_quantity)

    def test_zero_velocity_holds(self):
        owner = seller()
        item = product(owner)
        service = ReorderRecommendationService(repository=FakeReorderRepository())

        rec = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=10),
            sales_velocity=velocity(owner, item, rate="0.0000"),
            stockout_prediction=stockout(owner, item),
            as_of_date=date(2026, 6, 29),
        ).recommendation

        self.assertEqual(ReorderRecommendationAction.HOLD, rec.action)
        self.assertEqual(ReorderRecommendationStatus.OPEN, rec.recommendation_status)

    def test_missing_lead_time_uses_default_and_reduces_confidence(self):
        owner = seller()
        item = product(owner, lead_time=None)
        service = ReorderRecommendationService(repository=FakeReorderRepository())

        rec = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=40),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            stockout_prediction=stockout(owner, item),
            as_of_date=date(2026, 6, 29),
        ).recommendation

        self.assertTrue(rec.evidence["supplier_lead_time_defaulted"])
        self.assertLess(rec.confidence_score, Decimal("91.25"))

    def test_insufficient_sales_data(self):
        owner = seller()
        item = product(owner)
        service = ReorderRecommendationService(repository=FakeReorderRepository())

        rec = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=40),
            sales_velocity=velocity(owner, item, rate="10.0000", status=SalesVelocityDataStatus.INSUFFICIENT),
            stockout_prediction=stockout(owner, item),
            as_of_date=date(2026, 6, 29),
        ).recommendation

        self.assertEqual(ReorderRecommendationStatus.INSUFFICIENT_DATA, rec.recommendation_status)
        self.assertEqual(0, rec.recommended_quantity)

    def test_duplicate_retry_and_history_preservation(self):
        owner = seller()
        item = product(owner)
        repo = FakeReorderRepository()
        repo.products = [(item, owner)]
        repo.inventory[item.id] = inventory(owner, item, on_hand=40)
        repo.velocities[item.id] = velocity(owner, item, rate="10.0000")
        repo.stockouts[item.id] = stockout(owner, item)
        service = ReorderRecommendationService(repository=repo)

        first = service.calculate_for_batch(as_of_date=date(2026, 6, 29))
        duplicate = service.calculate_for_batch(as_of_date=date(2026, 6, 29))
        next_day = service.calculate_for_batch(as_of_date=date(2026, 6, 30))

        self.assertEqual(1, first.created_count)
        self.assertEqual(0, duplicate.created_count)
        self.assertEqual(1, duplicate.skipped_count)
        self.assertEqual(1, next_day.created_count)
        self.assertEqual(2, len(repo.rows))

    def test_status_transitions_and_seller_isolation(self):
        owner = seller()
        other = seller()
        item = product(owner)
        repo = FakeReorderRepository()
        service = ReorderRecommendationService(repository=repo)
        rec = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=40),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            stockout_prediction=stockout(owner, item),
            as_of_date=date(2026, 6, 29),
        ).recommendation

        acknowledged = service.transition_status(
            seller_id=owner.id,
            recommendation_id=rec.id,
            status=ReorderRecommendationStatus.ACKNOWLEDGED,
        )
        self.assertEqual(ReorderRecommendationStatus.ACKNOWLEDGED, acknowledged.recommendation_status)
        ordered = service.transition_status(
            seller_id=owner.id,
            recommendation_id=rec.id,
            status=ReorderRecommendationStatus.ORDERED,
        )
        self.assertEqual(ReorderRecommendationStatus.ORDERED, ordered.recommendation_status)
        dismissed = service.transition_status(
            seller_id=owner.id,
            recommendation_id=rec.id,
            status=ReorderRecommendationStatus.DISMISSED,
        )

        self.assertEqual(ReorderRecommendationStatus.DISMISSED, dismissed.recommendation_status)
        with self.assertRaises(ReorderRecommendationNotFoundError):
            service.transition_status(
                seller_id=other.id,
                recommendation_id=rec.id,
                status=ReorderRecommendationStatus.ACKNOWLEDGED,
            )


if __name__ == "__main__":
    unittest.main()
