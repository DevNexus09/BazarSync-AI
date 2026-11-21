from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest
from uuid import uuid4

from app.models.competitor import Competitor
from app.models.scrape_run import ScrapeRun
from app.services.competitor_snapshot_service import (
    CompetitorObservation,
    CompetitorSnapshotService,
    normalize_stock_status,
)


class CompetitorSnapshotServiceTest(unittest.TestCase):
    def test_acceptance_two_runs_create_separate_immutable_snapshots(self) -> None:
        product_id = uuid4()
        competitor_id = uuid4()
        competitor_one = _competitor(product_id=product_id, competitor_id=competitor_id, price=Decimal("320.00"))
        competitor_two = _competitor(product_id=product_id, competitor_id=competitor_id, price=Decimal("290.00"))
        service = CompetitorSnapshotService.__new__(CompetitorSnapshotService)

        first_captured_at = datetime(2026, 6, 29, 9, 0, tzinfo=timezone.utc)
        second_captured_at = datetime(2026, 6, 29, 10, 0, tzinfo=timezone.utc)
        first = service._build_snapshots(
            scrape_run=_scrape_run(product_id=product_id),
            competitors=[competitor_one],
            captured_at=first_captured_at,
        )[0]
        second = service._build_snapshots(
            scrape_run=_scrape_run(product_id=product_id),
            competitors=[competitor_two],
            captured_at=second_captured_at,
        )[0]

        self.assertNotEqual(first.scrape_run_id, second.scrape_run_id)
        self.assertEqual(first.competitor_id, second.competitor_id)
        self.assertEqual(first.price, Decimal("320.00"))
        self.assertEqual(second.price, Decimal("290.00"))
        self.assertEqual(first.stock_status, "IN_STOCK")
        self.assertEqual(second.stock_status, "IN_STOCK")
        self.assertLess(first.captured_at, second.captured_at)
        self.assertEqual(first.price, Decimal("320.00"))

    def test_missing_stock_status_becomes_unknown(self) -> None:
        self.assertEqual(normalize_stock_status(None), "UNKNOWN")
        self.assertEqual(normalize_stock_status(""), "UNKNOWN")
        self.assertEqual(normalize_stock_status("unparseable"), "UNKNOWN")

    def test_naive_field_timestamps_are_not_persisted_as_observations(self) -> None:
        product_id = uuid4()
        competitor = _competitor(product_id=product_id)
        naive = datetime(2026, 6, 29, 9, 0)
        service = CompetitorSnapshotService.__new__(CompetitorSnapshotService)
        snapshot, = service._build_snapshots(
            scrape_run=_scrape_run(product_id=product_id),
            competitors=[competitor],
            captured_at=naive.replace(tzinfo=timezone.utc),
            observations={
                competitor.id: CompetitorObservation(
                    price=Decimal("320.00"), rating=None, review_count=None, stock_status="in_stock",
                    price_observed_at=naive, stock_observed_at=naive,
                ),
            },
        )
        self.assertIsNone(snapshot.price_observed_at)
        self.assertIsNone(snapshot.stock_observed_at)

    def test_negative_price_is_rejected_before_snapshot_insert(self) -> None:
        product_id = uuid4()
        competitor = _competitor(product_id=product_id, price=Decimal("-1.00"))
        service = CompetitorSnapshotService.__new__(CompetitorSnapshotService)

        with self.assertRaisesRegex(ValueError, "price cannot be negative"):
            service._build_snapshots(
                scrape_run=_scrape_run(product_id=product_id),
                competitors=[competitor],
                captured_at=datetime.now(timezone.utc),
            )

    def test_negative_review_count_is_rejected_before_snapshot_insert(self) -> None:
        product_id = uuid4()
        competitor = _competitor(product_id=product_id, rating_count=-1)
        service = CompetitorSnapshotService.__new__(CompetitorSnapshotService)

        with self.assertRaisesRegex(ValueError, "review_count cannot be negative"):
            service._build_snapshots(
                scrape_run=_scrape_run(product_id=product_id),
                competitors=[competitor],
                captured_at=datetime.now(timezone.utc),
            )


def _scrape_run(*, product_id):
    return ScrapeRun(
        id=uuid4(),
        seller_id=uuid4(),
        product_id=product_id,
        marketplace="Daraz Bangladesh",
        run_key=f"test:{uuid4()}",
        status="RUNNING",
    )


def _competitor(
    *,
    product_id,
    competitor_id=None,
    price: Decimal = Decimal("320.00"),
    rating_count: int | None = 3,
) -> Competitor:
    return Competitor(
        id=competitor_id or uuid4(),
        scrape_run_id=uuid4(),
        product_id=product_id,
        competitor_title="Competitor A",
        competitor_price=price,
        competitor_rating=Decimal("4.50"),
        rating_count=rating_count,
        stock_status="in_stock",
        marketplace="Daraz Bangladesh",
        product_url=f"https://example.test/{uuid4()}",
    )


if __name__ == "__main__":
    unittest.main()
