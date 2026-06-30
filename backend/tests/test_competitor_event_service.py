from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from uuid import uuid4

from app.models.competitor_event import CompetitorEventType
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.scrape_run import ScrapeRun
from app.services.competitor_event_service import CompetitorEventConfig, CompetitorEventService


class CompetitorEventServiceTest(unittest.TestCase):
    def test_acceptance_scenario(self) -> None:
        product_id = uuid4()
        seller_id = uuid4()
        a, b, c, d = uuid4(), uuid4(), uuid4(), uuid4()
        run1 = _run(product_id=product_id, seller_id=seller_id, index=1)
        run2 = _run(product_id=product_id, seller_id=seller_id, index=2)
        run3 = _run(product_id=product_id, seller_id=seller_id, index=3)
        snapshots = {
            run1.id: {
                a: _snapshot(run1, a, "320.00", "IN_STOCK"),
                b: _snapshot(run1, b, "500.00", "IN_STOCK"),
                c: _snapshot(run1, c, "450.00", "IN_STOCK"),
            },
            run2.id: {
                a: _snapshot(run2, a, "290.00", "IN_STOCK"),
                b: _snapshot(run2, b, "500.00", "OUT_OF_STOCK"),
                d: _snapshot(run2, d, "400.00", "IN_STOCK"),
            },
            run3.id: {
                a: _snapshot(run3, a, "290.00", "IN_STOCK"),
                b: _snapshot(run3, b, "500.00", "OUT_OF_STOCK"),
                d: _snapshot(run3, d, "400.00", "IN_STOCK"),
            },
        }
        service, events = _service([run1, run2, run3], snapshots)

        result2 = service.generate_for_scrape_run(run2.id)
        self.assertEqual(result2.generated_count, 3)
        self.assertCountEqual(
            [event.event_type for event in events.items],
            [
                CompetitorEventType.PRICE_DROP,
                CompetitorEventType.OUT_OF_STOCK,
                CompetitorEventType.NEW_COMPETITOR,
            ],
        )

        result3 = service.generate_for_scrape_run(run3.id)
        self.assertEqual(result3.generated_count, 1)
        self.assertEqual(events.items[-1].event_type, CompetitorEventType.COMPETITOR_REMOVED)
        self.assertEqual(events.items[-1].competitor_id, c)

        retry = service.generate_for_scrape_run(run3.id)
        self.assertEqual(retry.generated_count, 0)
        self.assertEqual(len(events.items), 4)

    def test_first_run_is_baseline(self) -> None:
        run1 = _run(index=1)
        service, events = _service([run1], {run1.id: {uuid4(): _snapshot(run1, uuid4(), "10", "IN_STOCK")}})
        result = service.generate_for_scrape_run(run1.id)
        self.assertEqual(result.generated_count, 0)
        self.assertEqual(result.skipped_reason, "baseline")
        self.assertEqual(events.items, [])

    def test_price_rise_and_percentage(self) -> None:
        competitor_id = uuid4()
        run1 = _run(index=1)
        run2 = _run(product_id=run1.product_id, seller_id=run1.seller_id, index=2)
        service, events = _service(
            [run1, run2],
            {
                run1.id: {competitor_id: _snapshot(run1, competitor_id, "100.00", "IN_STOCK")},
                run2.id: {competitor_id: _snapshot(run2, competitor_id, "125.00", "IN_STOCK")},
            },
        )
        service.generate_for_scrape_run(run2.id)
        self.assertEqual(events.items[0].event_type, CompetitorEventType.PRICE_RISE)
        self.assertEqual(events.items[0].price_change_amount, Decimal("25.00"))
        self.assertEqual(events.items[0].price_change_percent, Decimal("25.0000"))

    def test_no_event_below_threshold(self) -> None:
        competitor_id = uuid4()
        run1 = _run(index=1)
        run2 = _run(product_id=run1.product_id, seller_id=run1.seller_id, index=2)
        service, events = _service(
            [run1, run2],
            {
                run1.id: {competitor_id: _snapshot(run1, competitor_id, "100.00", "IN_STOCK")},
                run2.id: {competitor_id: _snapshot(run2, competitor_id, "99.50", "IN_STOCK")},
            },
            config=CompetitorEventConfig(Decimal("1.00"), Decimal("1.00"), 2),
        )
        service.generate_for_scrape_run(run2.id)
        self.assertEqual(events.items, [])

    def test_back_in_stock(self) -> None:
        competitor_id = uuid4()
        run1 = _run(index=1)
        run2 = _run(product_id=run1.product_id, seller_id=run1.seller_id, index=2)
        service, events = _service(
            [run1, run2],
            {
                run1.id: {competitor_id: _snapshot(run1, competitor_id, "10", "OUT_OF_STOCK")},
                run2.id: {competitor_id: _snapshot(run2, competitor_id, "10", "IN_STOCK")},
            },
        )
        service.generate_for_scrape_run(run2.id)
        self.assertEqual(events.items[0].event_type, CompetitorEventType.BACK_IN_STOCK)

    def test_unknown_stock_status_does_not_generate_stock_event(self) -> None:
        competitor_id = uuid4()
        run1 = _run(index=1)
        run2 = _run(product_id=run1.product_id, seller_id=run1.seller_id, index=2)
        service, events = _service(
            [run1, run2],
            {
                run1.id: {competitor_id: _snapshot(run1, competitor_id, "10", "IN_STOCK")},
                run2.id: {competitor_id: _snapshot(run2, competitor_id, "10", "UNKNOWN")},
            },
        )
        service.generate_for_scrape_run(run2.id)
        self.assertEqual(events.items, [])

    def test_failed_and_partial_runs_are_ignored(self) -> None:
        failed = _run(index=1, status="FAILED")
        partial = _run(index=2, status="PARTIAL")
        service, events = _service([failed, partial], {})
        self.assertEqual(service.generate_for_scrape_run(failed.id).skipped_reason, "not_completed")
        self.assertEqual(service.generate_for_scrape_run(partial.id).skipped_reason, "not_completed")
        self.assertEqual(events.items, [])

    def test_seller_scope_is_copied_to_event(self) -> None:
        competitor_id = uuid4()
        seller_id = uuid4()
        run1 = _run(seller_id=seller_id, index=1)
        run2 = _run(product_id=run1.product_id, seller_id=seller_id, index=2)
        service, events = _service(
            [run1, run2],
            {
                run1.id: {competitor_id: _snapshot(run1, competitor_id, "10", "IN_STOCK")},
                run2.id: {competitor_id: _snapshot(run2, competitor_id, "8", "IN_STOCK")},
            },
        )
        service.generate_for_scrape_run(run2.id)
        self.assertEqual(events.items[0].seller_id, seller_id)


def _service(runs, snapshots, config=None):
    service = CompetitorEventService.__new__(CompetitorEventService)
    service._db = FakeDb()
    service._config = config or CompetitorEventConfig(Decimal("1.00"), Decimal("1.00"), 2)
    service._events = FakeEventRepo()
    service._snapshots = FakeSnapshotRepo(runs, snapshots)
    service._log = NullLog()
    return service, service._events


def _run(*, product_id=None, seller_id=None, index: int, status="COMPLETED") -> ScrapeRun:
    now = datetime(2026, 6, 29, tzinfo=timezone.utc) + timedelta(hours=index)
    return ScrapeRun(
        id=uuid4(),
        seller_id=seller_id or uuid4(),
        product_id=product_id or uuid4(),
        marketplace="Daraz Bangladesh",
        run_key=f"run:{index}:{uuid4()}",
        status=status,
        created_at=now,
        completed_at=now,
        finished_at=now,
    )


def _snapshot(run: ScrapeRun, competitor_id, price: str, stock_status: str) -> CompetitorSnapshot:
    return CompetitorSnapshot(
        id=uuid4(),
        scrape_run_id=run.id,
        competitor_id=competitor_id,
        product_id=run.product_id,
        price=Decimal(price),
        currency="BDT",
        stock_status=stock_status,
        captured_at=run.completed_at,
    )


class FakeDb:
    def commit(self):
        pass

    def rollback(self):
        pass


class FakeEventRepo:
    def __init__(self):
        self.items = []

    def existing_dedupe_keys(self, keys):
        existing = {event.dedupe_key for event in self.items}
        return existing & set(keys)

    def add_all(self, events):
        self.items.extend(events)

    def has_removal_event(self, *, product_id, competitor_id):
        return any(
            event.product_id == product_id
            and event.competitor_id == competitor_id
            and event.event_type == CompetitorEventType.COMPETITOR_REMOVED
            for event in self.items
        )


class FakeSnapshotRepo:
    def __init__(self, runs, snapshots):
        self.runs = {run.id: run for run in runs}
        self.ordered = sorted(runs, key=lambda run: run.created_at, reverse=True)
        self.snapshots = snapshots

    def get_completed_run(self, scrape_run_id):
        run = self.runs.get(scrape_run_id)
        return run if run and run.status == "COMPLETED" else None

    def previous_completed_run(self, current_run):
        candidates = [
            run for run in self.runs.values()
            if run.status == "COMPLETED"
            and run.product_id == current_run.product_id
            and run.seller_id == current_run.seller_id
            and run.created_at < current_run.created_at
        ]
        return max(candidates, key=lambda run: run.created_at, default=None)

    def recent_completed_runs(self, current_run, *, limit):
        candidates = [
            run for run in self.runs.values()
            if run.status == "COMPLETED"
            and run.product_id == current_run.product_id
            and run.seller_id == current_run.seller_id
            and run.created_at <= current_run.created_at
        ]
        return sorted(candidates, key=lambda run: run.created_at, reverse=True)[:limit]

    def snapshots_by_run(self, scrape_run_ids):
        return {run_id: self.snapshots.get(run_id, {}) for run_id in scrape_run_ids}

    def historical_competitor_ids_before(self, current_run):
        competitor_ids = set()
        for run in self.runs.values():
            if (
                run.status == "COMPLETED"
                and run.product_id == current_run.product_id
                and run.seller_id == current_run.seller_id
                and run.created_at < current_run.created_at
            ):
                competitor_ids.update(self.snapshots.get(run.id, {}))
        return competitor_ids


class NullLog:
    def info(self, *args, **kwargs):
        pass


if __name__ == "__main__":
    unittest.main()
