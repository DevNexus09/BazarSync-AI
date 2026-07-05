from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.models.inventory_aging import InventoryAgeSource
from app.services.inventory_aging_service import InventoryAgingService, InventoryLotState


class FakeInventoryAgingRepository:
    def __init__(self, *, fail_product_ids=None) -> None:
        self.products = []
        self.rows = {}
        self.inventory_by_product = {}
        self.first_positive_by_product = {}
        self.lots_by_product = {}
        self.fail_product_ids = set(fail_product_ids or [])

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

    def first_positive_inventory_for_products(self, *, seller_id, product_ids, as_of_date):
        return {
            product_id: inventory
            for product_id, inventory in self.first_positive_by_product.items()
            if product_id in product_ids
            and inventory.seller_id == seller_id
            and inventory.snapshot_date <= as_of_date
            and inventory.quantity_on_hand > 0
        }

    def lot_states_for_products(self, *, seller_id, product_ids, as_of_date):
        return {
            product_id: lots
            for product_id, lots in self.lots_by_product.items()
            if product_id in product_ids
        }

    def add_idempotent(self, snapshot):
        if snapshot.product_id in self.fail_product_ids:
            raise RuntimeError("simulated failure")
        key = (snapshot.product_id, snapshot.as_of_date, snapshot.calculation_version)
        existing = self.rows.get(key)
        if existing:
            return existing, False
        self.rows[key] = snapshot
        return snapshot, True

    def latest(self, *, seller_id, product_id, calculation_version):
        rows = [
            row
            for row in self.rows.values()
            if row.seller_id == seller_id
            and row.product_id == product_id
            and (calculation_version is None or row.calculation_version == calculation_version)
        ]
        rows.sort(key=lambda row: (row.as_of_date, row.calculated_at), reverse=True)
        return rows[0] if rows else None

    def history(self, *, seller_id, product_id, from_date, to_date, calculation_version, order, limit, offset):
        rows = [
            row
            for row in self.rows.values()
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


def product(owner, *, stock=10, product_id=None, created_at=None):
    return SimpleNamespace(
        id=product_id or uuid4(),
        seller_id=owner.id,
        seller=owner,
        stock_quantity=stock,
        created_at=created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def inventory(owner, item, *, on_hand, reserved=0, snapshot_date=date(2026, 6, 29)):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        snapshot_date=snapshot_date,
        captured_at=datetime(2026, 6, 29, 8, tzinfo=timezone.utc),
        quantity_on_hand=on_hand,
        quantity_reserved=reserved,
        quantity_available=on_hand - reserved,
        quantity_incoming=0,
    )


class InventoryAgingServiceTests(unittest.TestCase):
    def test_exact_lot_based_age_and_weighted_average(self):
        owner = seller()
        item = product(owner, stock=10)
        service = InventoryAgingService(repository=FakeInventoryAgingRepository(), bucket_edges=[30, 45, 60, 90, 180])

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=10),
            as_of_date=date(2026, 6, 30),
            lots=[
                InventoryLotState(received_date=date(2026, 6, 20), remaining_quantity=4),
                InventoryLotState(received_date=date(2026, 5, 31), remaining_quantity=6),
            ],
        )

        self.assertFalse(outcome.snapshot.is_estimated)
        self.assertEqual(InventoryAgeSource.INVENTORY_LOT, outcome.snapshot.age_source)
        self.assertEqual(30, outcome.snapshot.oldest_age_days)
        self.assertEqual(10, outcome.snapshot.newest_age_days)
        self.assertEqual(Decimal("22.0000"), outcome.snapshot.weighted_average_age_days)

    def test_multiple_lots_are_bucketed_by_age(self):
        owner = seller()
        item = product(owner, stock=9)
        service = InventoryAgingService(repository=FakeInventoryAgingRepository(), bucket_edges=[30, 45, 60, 90, 180])

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=9),
            as_of_date=date(2026, 6, 30),
            lots=[
                InventoryLotState(received_date=date(2026, 6, 30), remaining_quantity=1),
                InventoryLotState(received_date=date(2026, 5, 30), remaining_quantity=2),
                InventoryLotState(received_date=date(2026, 5, 15), remaining_quantity=3),
                InventoryLotState(received_date=date(2026, 4, 1), remaining_quantity=4),
            ],
        )

        self.assertEqual(1, outcome.snapshot.age_buckets["0_30"]["quantity"])
        self.assertEqual(2, outcome.snapshot.age_buckets["31_45"]["quantity"])
        self.assertEqual(3, outcome.snapshot.age_buckets["46_60"]["quantity"])
        self.assertEqual(4, outcome.snapshot.age_buckets["61_90"]["quantity"])

    def test_reserved_stock_is_excluded_from_eligible_quantity(self):
        owner = seller()
        item = product(owner, stock=20)
        service = InventoryAgingService(repository=FakeInventoryAgingRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=20, reserved=6),
            first_positive_snapshot=inventory(owner, item, on_hand=20, snapshot_date=date(2026, 6, 1)),
            as_of_date=date(2026, 6, 30),
        )

        self.assertEqual(14, outcome.snapshot.eligible_unsold_quantity)
        self.assertEqual(14, outcome.snapshot.age_buckets["0_30"]["quantity"])

    def test_zero_available_stock_returns_unavailable_age_not_zero(self):
        owner = seller()
        item = product(owner, stock=5)
        service = InventoryAgingService(repository=FakeInventoryAgingRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            inventory_snapshot=inventory(owner, item, on_hand=5, reserved=5),
            as_of_date=date(2026, 6, 30),
        )

        self.assertEqual(0, outcome.snapshot.eligible_unsold_quantity)
        self.assertEqual(InventoryAgeSource.UNAVAILABLE, outcome.snapshot.age_source)
        self.assertIsNone(outcome.snapshot.oldest_age_days)
        self.assertIsNone(outcome.snapshot.weighted_average_age_days)

    def test_first_positive_snapshot_fallback_is_estimated(self):
        owner = seller()
        item = product(owner, stock=12)
        service = InventoryAgingService(repository=FakeInventoryAgingRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            first_positive_snapshot=inventory(owner, item, on_hand=1, snapshot_date=date(2026, 6, 1)),
            as_of_date=date(2026, 6, 30),
        )

        self.assertTrue(outcome.snapshot.is_estimated)
        self.assertEqual(InventoryAgeSource.FIRST_POSITIVE_SNAPSHOT, outcome.snapshot.age_source)
        self.assertEqual(29, outcome.snapshot.oldest_age_days)
        self.assertEqual(Decimal("29.0000"), outcome.snapshot.weighted_average_age_days)

    def test_product_created_fallback_is_estimated_with_lower_confidence(self):
        owner = seller()
        item = product(owner, stock=12, created_at=datetime(2026, 6, 10, tzinfo=timezone.utc))
        service = InventoryAgingService(repository=FakeInventoryAgingRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            as_of_date=date(2026, 6, 30),
        )

        self.assertTrue(outcome.snapshot.is_estimated)
        self.assertEqual(InventoryAgeSource.PRODUCT_CREATED_AT_ESTIMATE, outcome.snapshot.age_source)
        self.assertEqual(20, outcome.snapshot.oldest_age_days)
        self.assertLess(outcome.snapshot.confidence_score, Decimal("70"))

    def test_completely_unavailable_age(self):
        owner = seller()
        item = product(owner, stock=8, created_at=None)
        item.created_at = None
        service = InventoryAgingService(repository=FakeInventoryAgingRepository())

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            as_of_date=date(2026, 6, 30),
        )

        self.assertEqual(InventoryAgeSource.UNAVAILABLE, outcome.snapshot.age_source)
        self.assertIsNone(outcome.snapshot.newest_age_days)

    def test_age_bucket_boundaries(self):
        owner = seller()
        item = product(owner, stock=3)
        service = InventoryAgingService(repository=FakeInventoryAgingRepository(), bucket_edges=[30, 45])

        outcome = service.calculate_for_product(
            product=item,
            seller=owner,
            as_of_date=date(2026, 6, 30),
            lots=[
                InventoryLotState(received_date=date(2026, 5, 31), remaining_quantity=1),
                InventoryLotState(received_date=date(2026, 5, 16), remaining_quantity=1),
                InventoryLotState(received_date=date(2026, 5, 15), remaining_quantity=1),
            ],
        )

        self.assertEqual(1, outcome.snapshot.age_buckets["0_30"]["quantity"])
        self.assertEqual(1, outcome.snapshot.age_buckets["31_45"]["quantity"])
        self.assertEqual(1, outcome.snapshot.age_buckets["46_plus"]["quantity"])

    def test_seller_timezone_business_date(self):
        owner = seller(timezone_name="Asia/Dhaka")
        business_date = InventoryAgingService.business_date_for_seller(
            owner,
            datetime(2026, 6, 29, 19, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(date(2026, 6, 30), business_date)

    def test_duplicate_task_retry_preserves_historical_row(self):
        owner = seller()
        item = product(owner, stock=10)
        repo = FakeInventoryAgingRepository()
        service = InventoryAgingService(repository=repo)

        first = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 30))
        item.stock_quantity = 99
        second = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 30))

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.snapshot.quantity_on_hand, second.snapshot.quantity_on_hand)
        self.assertEqual(1, len(repo.rows))

    def test_seller_isolation_in_history(self):
        first_seller = seller()
        second_seller = seller()
        item = product(first_seller, stock=10)
        repo = FakeInventoryAgingRepository()
        service = InventoryAgingService(repository=repo)
        service.calculate_for_product(product=item, seller=first_seller, as_of_date=date(2026, 6, 30))

        rows, total = service.aging_history(
            seller_id=second_seller.id,
            product_id=item.id,
            from_date=None,
            to_date=None,
            calculation_version=None,
            order="desc",
            limit=20,
            offset=0,
        )

        self.assertEqual(0, total)
        self.assertEqual([], rows)

    def test_backfill_idempotency_and_large_batch_processing(self):
        owner = seller()
        first = product(owner, stock=5)
        second = product(owner, stock=6)
        repo = FakeInventoryAgingRepository()
        repo.products = [(first, owner), (second, owner)]
        service = InventoryAgingService(repository=repo)

        dry_run = service.backfill_baseline(batch_size=1, as_of_date=date(2026, 6, 30), dry_run=True)
        created = service.backfill_baseline(batch_size=1, as_of_date=date(2026, 6, 30))
        repeated = service.backfill_baseline(batch_size=1, as_of_date=date(2026, 6, 30))

        self.assertEqual(2, dry_run.dry_run_count)
        self.assertEqual(2, created.calculated_count)
        self.assertEqual(0, repeated.calculated_count)
        self.assertEqual(2, repeated.skipped_count)

    def test_batch_processing_continues_after_one_product_failure(self):
        owner = seller()
        failed = product(owner, stock=5)
        healthy = product(owner, stock=6)
        repo = FakeInventoryAgingRepository(fail_product_ids={failed.id})
        repo.products = [(failed, owner), (healthy, owner)]
        service = InventoryAgingService(repository=repo)

        result = service.calculate_batch(batch_size=1, as_of_date=date(2026, 6, 30))

        self.assertEqual(1, result.calculated_count)
        self.assertEqual(1, result.failed_count)


if __name__ == "__main__":
    unittest.main()
