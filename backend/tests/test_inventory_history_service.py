from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.models.inventory_history import InventorySnapshotSource
from app.services.inventory_history_service import (
    InvalidInventoryQuantityError,
    InventoryHistoryService,
)


class FakeInventoryHistoryRepository:
    def __init__(self, rows=None, fail_product_ids=None) -> None:
        self.rows = dict(rows or {})
        self.products = []
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

    def add_idempotent(self, snapshot):
        if snapshot.product_id in self.fail_product_ids:
            raise RuntimeError("simulated product failure")
        key = (snapshot.seller_id, snapshot.product_id, snapshot.snapshot_date)
        existing = self.rows.get(key)
        if existing:
            return existing, False
        self.rows[key] = snapshot
        return snapshot, True

    def list_for_product(self, *, seller_id, product_id, from_date, to_date, order, limit, offset):
        items = [
            row
            for (row_seller_id, row_product_id, _), row in self.rows.items()
            if row_seller_id == seller_id and row_product_id == product_id
        ]
        if from_date:
            items = [row for row in items if row.snapshot_date >= from_date]
        if to_date:
            items = [row for row in items if row.snapshot_date <= to_date]
        items.sort(key=lambda row: (row.snapshot_date, row.captured_at), reverse=order == "desc")
        return items[offset : offset + limit], len(items)

    def latest_for_product(self, *, seller_id, product_id):
        items, _ = self.list_for_product(
            seller_id=seller_id,
            product_id=product_id,
            from_date=None,
            to_date=None,
            order="desc",
            limit=1,
            offset=0,
        )
        return items[0] if items else None


def seller(seller_id=None, timezone_name=None):
    return SimpleNamespace(id=seller_id or uuid4(), timezone=timezone_name)


def product(owner, *, stock=10, product_id=None):
    item = SimpleNamespace(
        id=product_id or uuid4(),
        seller_id=owner.id,
        stock_quantity=stock,
        seller=owner,
    )
    return item


class InventoryHistoryServiceTests(unittest.TestCase):
    def test_daily_snapshot_creation(self):
        owner = seller()
        item = product(owner, stock=14)
        repo = FakeInventoryHistoryRepository()
        service = InventoryHistoryService(repository=repo)

        outcome = service.create_snapshot_for_product(
            product=item,
            seller=owner,
            snapshot_date=date(2026, 6, 29),
            captured_at=datetime(2026, 6, 29, 9, tzinfo=timezone.utc),
        )

        self.assertTrue(outcome.created)
        self.assertEqual(14, outcome.snapshot.quantity_on_hand)
        self.assertEqual(14, outcome.snapshot.quantity_available)
        self.assertEqual(InventorySnapshotSource.DAILY_SNAPSHOT, outcome.snapshot.source)

    def test_duplicate_daily_task_retry_returns_existing_snapshot(self):
        owner = seller()
        item = product(owner, stock=10)
        repo = FakeInventoryHistoryRepository()
        service = InventoryHistoryService(repository=repo)
        first = service.create_snapshot_for_product(
            product=item,
            seller=owner,
            snapshot_date=date(2026, 6, 29),
        )
        item.stock_quantity = 20
        second = service.create_snapshot_for_product(
            product=item,
            seller=owner,
            snapshot_date=date(2026, 6, 29),
        )

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(10, second.snapshot.quantity_on_hand)
        self.assertEqual(1, len(repo.rows))

    def test_multiple_sellers_are_isolated(self):
        first_seller = seller()
        second_seller = seller()
        first_product = product(first_seller, stock=7)
        second_product = product(second_seller, stock=9)
        repo = FakeInventoryHistoryRepository()
        service = InventoryHistoryService(repository=repo)

        service.create_snapshot_for_product(
            product=first_product,
            seller=first_seller,
            snapshot_date=date(2026, 6, 29),
        )
        service.create_snapshot_for_product(
            product=second_product,
            seller=second_seller,
            snapshot_date=date(2026, 6, 29),
        )

        first_items, first_total = service.list_product_history(
            seller_id=first_seller.id,
            product_id=first_product.id,
            from_date=None,
            to_date=None,
            order="desc",
            limit=10,
            offset=0,
        )
        leaked_items, leaked_total = service.list_product_history(
            seller_id=second_seller.id,
            product_id=first_product.id,
            from_date=None,
            to_date=None,
            order="desc",
            limit=10,
            offset=0,
        )

        self.assertEqual(1, first_total)
        self.assertEqual(7, first_items[0].quantity_on_hand)
        self.assertEqual(0, leaked_total)
        self.assertEqual([], leaked_items)

    def test_reserved_and_incoming_stock(self):
        owner = seller()
        item = product(owner, stock=20)
        service = InventoryHistoryService(repository=FakeInventoryHistoryRepository())

        outcome = service.create_snapshot_for_product(
            product=item,
            seller=owner,
            snapshot_date=date(2026, 6, 29),
            quantity_reserved=6,
            quantity_incoming=12,
        )

        self.assertEqual(14, outcome.snapshot.quantity_available)
        self.assertEqual(12, outcome.snapshot.quantity_incoming)

    def test_timezone_date_boundaries(self):
        owner = seller(timezone_name="Asia/Dhaka")
        captured_at = datetime(2026, 6, 28, 19, 0, tzinfo=timezone.utc)

        business_date = InventoryHistoryService.business_date_for_seller(owner, captured_at)

        self.assertEqual(date(2026, 6, 29), business_date)

    def test_pagination_timeline_ordering_and_date_filtering(self):
        owner = seller()
        item = product(owner)
        repo = FakeInventoryHistoryRepository()
        service = InventoryHistoryService(repository=repo)
        for day, stock in ((27, 5), (28, 6), (29, 7)):
            item.stock_quantity = stock
            service.create_snapshot_for_product(
                product=item,
                seller=owner,
                snapshot_date=date(2026, 6, day),
                captured_at=datetime(2026, 6, day, 9, tzinfo=timezone.utc),
            )

        items, total = service.list_product_history(
            seller_id=owner.id,
            product_id=item.id,
            from_date=date(2026, 6, 28),
            to_date=date(2026, 6, 29),
            order="asc",
            limit=1,
            offset=1,
        )

        self.assertEqual(2, total)
        self.assertEqual([date(2026, 6, 29)], [row.snapshot_date for row in items])

    def test_backfill_idempotency_and_dry_run(self):
        owner = seller()
        first = product(owner, stock=3)
        second = product(owner, stock=4)
        repo = FakeInventoryHistoryRepository()
        repo.products = [(first, owner), (second, owner)]
        service = InventoryHistoryService(repository=repo)
        now = datetime(2026, 6, 29, 10, tzinfo=timezone.utc)

        dry_run = service.backfill_current_inventory(batch_size=1, now=now, dry_run=True)
        created = service.backfill_current_inventory(batch_size=1, now=now)
        repeated = service.backfill_current_inventory(batch_size=1, now=now)

        self.assertEqual(2, dry_run.dry_run_count)
        self.assertEqual(2, created.created_count)
        self.assertEqual(0, created.skipped_count)
        self.assertEqual(0, repeated.created_count)
        self.assertEqual(2, repeated.skipped_count)

    def test_batch_processing_continues_after_product_failure(self):
        owner = seller()
        failed = product(owner, stock=1)
        healthy = product(owner, stock=2)
        repo = FakeInventoryHistoryRepository(fail_product_ids={failed.id})
        repo.products = [(failed, owner), (healthy, owner)]
        service = InventoryHistoryService(repository=repo)

        result = service.capture_daily_snapshots(
            batch_size=1,
            now=datetime(2026, 6, 29, 10, tzinfo=timezone.utc),
        )

        self.assertEqual(1, result.created_count)
        self.assertEqual(0, result.skipped_count)
        self.assertEqual(1, result.failed_count)

    def test_invalid_quantity_constraints(self):
        owner = seller()
        item = product(owner, stock=-1)
        service = InventoryHistoryService(repository=FakeInventoryHistoryRepository())

        with self.assertRaises(InvalidInventoryQuantityError):
            service.create_snapshot_for_product(
                product=item,
                seller=owner,
                snapshot_date=date(2026, 6, 29),
            )


if __name__ == "__main__":
    unittest.main()
