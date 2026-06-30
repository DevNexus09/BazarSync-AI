from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.models.sales_velocity import SalesVelocityDataStatus
from app.models.stockout_prediction import StockoutPredictionStatus
from app.services.stockout_prediction_service import StockoutPredictionService


class FakeStockoutPredictionRepository:
    def __init__(self) -> None:
        self.products = []
        self.inventory_by_product = {}
        self.velocity_by_product = {}
        self.predictions = {}

    def iter_product_batches(self, *, batch_size, seller_id=None, product_id=None):
        filtered = [
            row
            for row in self.products
            if (seller_id is None or row[0].seller_id == seller_id)
            and (product_id is None or row[0].id == product_id)
        ]
        for index in range(0, len(filtered), batch_size):
            yield filtered[index : index + batch_size]

    def latest_inventory_for_products(self, *, seller_id, product_ids, as_of_date):
        return {
            product_id: inventory
            for product_id, inventory in self.inventory_by_product.items()
            if product_id in product_ids
            and inventory.seller_id == seller_id
            and inventory.snapshot_date <= as_of_date
        }

    def latest_velocity_for_products(self, *, seller_id, product_ids, as_of_date):
        return {
            product_id: velocity
            for product_id, velocity in self.velocity_by_product.items()
            if product_id in product_ids
            and velocity.seller_id == seller_id
            and velocity.as_of_date <= as_of_date
        }

    def add_idempotent(self, prediction):
        key = (prediction.product_id, prediction.as_of_date, prediction.calculation_version)
        existing = self.predictions.get(key)
        if existing:
            return existing, False
        self.predictions[key] = prediction
        return prediction, True

    def latest(self, *, seller_id, product_id, calculation_version):
        rows = [
            row
            for row in self.predictions.values()
            if row.seller_id == seller_id
            and row.product_id == product_id
            and (calculation_version is None or row.calculation_version == calculation_version)
        ]
        return sorted(rows, key=lambda row: (row.as_of_date, row.calculated_at), reverse=True)[0] if rows else None

    def history(self, *, seller_id, product_id, from_date, to_date, calculation_version, order, limit, offset):
        rows = [
            row
            for row in self.predictions.values()
            if row.seller_id == seller_id
            and row.product_id == product_id
            and (from_date is None or row.as_of_date >= from_date)
            and (to_date is None or row.as_of_date <= to_date)
            and (calculation_version is None or row.calculation_version == calculation_version)
        ]
        rows.sort(key=lambda row: row.as_of_date, reverse=order == "desc")
        return rows[offset : offset + limit], len(rows)


def seller(seller_id=None, timezone_name=None):
    return SimpleNamespace(id=seller_id or uuid4(), timezone=timezone_name)


def product(owner, *, stock=10, product_id=None):
    return SimpleNamespace(id=product_id or uuid4(), seller_id=owner.id, seller=owner, stock_quantity=stock)


def inventory(owner, item, *, on_hand, reserved=0, incoming=0, snapshot_date=date(2026, 6, 29)):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        snapshot_date=snapshot_date,
        quantity_on_hand=on_hand,
        quantity_reserved=reserved,
        quantity_incoming=incoming,
        captured_at=datetime(2026, 6, 29, 8, tzinfo=timezone.utc),
    )


def velocity(owner, item, *, rate, status=SalesVelocityDataStatus.SUFFICIENT, confidence=Decimal("90.00"), sales_days=10):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        as_of_date=date(2026, 6, 29),
        daily_sales_rate=Decimal(str(rate)),
        data_status=status,
        confidence_score=Decimal(str(confidence)),
        sales_days=sales_days,
    )


class StockoutPredictionServiceTests(unittest.TestCase):
    def test_40_units_at_10_per_day_equals_four_days(self):
        owner = seller()
        item = product(owner)
        service = StockoutPredictionService(repository=FakeStockoutPredictionRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=40),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            as_of_date=date(2026, 6, 29),
            calculated_at=datetime(2026, 6, 29, 10, tzinfo=timezone.utc),
        )

        self.assertEqual(StockoutPredictionStatus.PREDICTED, outcome.prediction.prediction_status)
        self.assertEqual("4.0000", str(outcome.prediction.days_remaining))
        self.assertEqual(date(2026, 7, 3), outcome.prediction.predicted_stockout_date)

    def test_zero_velocity_returns_no_recent_demand(self):
        owner = seller()
        item = product(owner)
        service = StockoutPredictionService(repository=FakeStockoutPredictionRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=40),
            sales_velocity=velocity(owner, item, rate="0.0000"),
            as_of_date=date(2026, 6, 29),
        )

        self.assertEqual(StockoutPredictionStatus.NO_RECENT_DEMAND, outcome.prediction.prediction_status)
        self.assertIsNone(outcome.prediction.predicted_stockout_date)

    def test_missing_velocity_returns_insufficient_data(self):
        owner = seller()
        item = product(owner)
        service = StockoutPredictionService(repository=FakeStockoutPredictionRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=40),
            sales_velocity=None,
            as_of_date=date(2026, 6, 29),
        )

        self.assertEqual(StockoutPredictionStatus.INSUFFICIENT_DATA, outcome.prediction.prediction_status)
        self.assertIsNone(outcome.prediction.predicted_stockout_date)

    def test_insufficient_sales_history_returns_insufficient_data(self):
        owner = seller()
        item = product(owner)
        service = StockoutPredictionService(repository=FakeStockoutPredictionRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=40),
            sales_velocity=velocity(owner, item, rate="4.0000", status=SalesVelocityDataStatus.INSUFFICIENT),
            as_of_date=date(2026, 6, 29),
        )

        self.assertEqual(StockoutPredictionStatus.INSUFFICIENT_DATA, outcome.prediction.prediction_status)
        self.assertLessEqual(outcome.prediction.confidence_score, 35)

    def test_zero_current_stock_is_already_out_of_stock(self):
        owner = seller()
        item = product(owner)
        service = StockoutPredictionService(repository=FakeStockoutPredictionRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=0),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            as_of_date=date(2026, 6, 29),
        )

        self.assertEqual(StockoutPredictionStatus.ALREADY_OUT_OF_STOCK, outcome.prediction.prediction_status)
        self.assertEqual("0.0000", str(outcome.prediction.days_remaining))
        self.assertEqual(date(2026, 6, 29), outcome.prediction.predicted_stockout_date)

    def test_reserved_quantity_reduces_inventory_position(self):
        owner = seller()
        item = product(owner)
        service = StockoutPredictionService(repository=FakeStockoutPredictionRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=50, reserved=10),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            as_of_date=date(2026, 6, 29),
        )

        self.assertEqual(40, outcome.prediction.inventory_position)
        self.assertEqual("4.0000", str(outcome.prediction.days_remaining))

    def test_confirmed_incoming_quantity_is_included_when_supplied(self):
        owner = seller()
        item = product(owner)
        service = StockoutPredictionService(repository=FakeStockoutPredictionRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=40, incoming=25),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            as_of_date=date(2026, 6, 29),
            confirmed_incoming_quantity=20,
        )

        self.assertEqual(20, outcome.prediction.quantity_incoming)
        self.assertEqual(60, outcome.prediction.inventory_position)
        self.assertEqual("6.0000", str(outcome.prediction.days_remaining))

    def test_unconfirmed_snapshot_incoming_is_excluded_by_default(self):
        owner = seller()
        item = product(owner)
        service = StockoutPredictionService(repository=FakeStockoutPredictionRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=40, incoming=25),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            as_of_date=date(2026, 6, 29),
        )

        self.assertEqual(0, outcome.prediction.quantity_incoming)
        self.assertEqual(40, outcome.prediction.inventory_position)
        self.assertIn("excluded", outcome.prediction.calculation_metadata["incoming_policy"])

    def test_negative_stock_is_preserved_and_treated_as_stocked_out(self):
        owner = seller()
        item = product(owner, stock=-5)
        service = StockoutPredictionService(repository=FakeStockoutPredictionRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=-5),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            as_of_date=date(2026, 6, 29),
        )

        self.assertEqual(-5, outcome.prediction.quantity_on_hand)
        self.assertEqual(StockoutPredictionStatus.ALREADY_OUT_OF_STOCK, outcome.prediction.prediction_status)

    def test_fractional_days_use_conservative_date_rounding(self):
        owner = seller()
        item = product(owner)
        service = StockoutPredictionService(repository=FakeStockoutPredictionRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=25),
            sales_velocity=velocity(owner, item, rate="10.0000"),
            as_of_date=date(2026, 6, 29),
        )

        self.assertEqual("2.5000", str(outcome.prediction.days_remaining))
        self.assertEqual(date(2026, 7, 1), outcome.prediction.predicted_stockout_date)

    def test_timezone_business_date(self):
        owner = seller(timezone_name="Asia/Dhaka")
        business_date = StockoutPredictionService.business_date_for_seller(
            owner,
            datetime(2026, 6, 28, 18, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(date(2026, 6, 29), business_date)

    def test_duplicate_task_retry_and_historical_preservation(self):
        owner = seller()
        item = product(owner)
        repo = FakeStockoutPredictionRepository()
        repo.products = [(item, owner)]
        repo.inventory_by_product[item.id] = inventory(owner, item, on_hand=40)
        repo.velocity_by_product[item.id] = velocity(owner, item, rate="10.0000")
        service = StockoutPredictionService(repository=repo)

        first = service.calculate_for_batch(as_of_date=date(2026, 6, 29))
        duplicate = service.calculate_for_batch(as_of_date=date(2026, 6, 29))
        next_day = service.calculate_for_batch(as_of_date=date(2026, 6, 30))

        self.assertEqual(1, first.created_count)
        self.assertEqual(0, duplicate.created_count)
        self.assertEqual(1, duplicate.skipped_count)
        self.assertEqual(1, next_day.created_count)
        self.assertEqual(2, len(repo.predictions))

    def test_seller_isolation(self):
        first_seller = seller()
        second_seller = seller()
        item = product(first_seller)
        repo = FakeStockoutPredictionRepository()
        repo.products = [(item, first_seller)]
        repo.inventory_by_product[item.id] = inventory(first_seller, item, on_hand=40)
        repo.velocity_by_product[item.id] = velocity(first_seller, item, rate="10.0000")
        service = StockoutPredictionService(repository=repo)
        service.calculate_for_batch(as_of_date=date(2026, 6, 29))

        first_latest = service.latest_prediction(seller_id=first_seller.id, product_id=item.id)
        leaked_latest = service.latest_prediction(seller_id=second_seller.id, product_id=item.id)

        self.assertIsNotNone(first_latest)
        self.assertIsNone(leaked_latest)


if __name__ == "__main__":
    unittest.main()
