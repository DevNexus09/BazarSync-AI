from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest
from uuid import uuid4

from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.scrape_run import ScrapeRun
from app.services.competitor_ranking_service import (
    RankingConfig,
    RankingWeights,
    CompetitorRankingService,
)


class CompetitorRankingServiceTest(unittest.TestCase):
    def test_formula_calculations(self) -> None:
        run = _run()
        cheap = uuid4()
        expensive = uuid4()
        service = _service()
        rankings, diagnostics = service._calculate_rankings(
            run,
            [
                _snapshot(run, cheap, "100.00", rating="5.00", reviews=100, stock="IN_STOCK"),
                _snapshot(run, expensive, "200.00", rating="0.00", reviews=0, stock="OUT_OF_STOCK"),
            ],
        )
        self.assertEqual(diagnostics.excluded_records, [])
        self.assertEqual(rankings[0].competitor_id, cheap)
        self.assertEqual(rankings[0].price_score, Decimal("100.0000"))
        self.assertEqual(rankings[0].rating_score, Decimal("100.0000"))
        self.assertEqual(rankings[0].review_score, Decimal("100.0000"))
        self.assertEqual(rankings[0].availability_score, Decimal("100.0000"))
        self.assertEqual(rankings[0].total_score, Decimal("100.0000"))
        self.assertEqual(rankings[1].total_score, Decimal("0.0000"))

    def test_equal_prices_and_one_competitor_get_price_score_100(self) -> None:
        run = _run()
        service = _service()
        rankings, _ = service._calculate_rankings(
            run,
            [_snapshot(run, uuid4(), "100.00"), _snapshot(run, uuid4(), "100.00")],
        )
        self.assertEqual([ranking.price_score for ranking in rankings], [Decimal("100.0000"), Decimal("100.0000")])

        one, _ = service._calculate_rankings(run, [_snapshot(run, uuid4(), "123.00")])
        self.assertEqual(one[0].price_score, Decimal("100.0000"))

    def test_all_review_counts_zero(self) -> None:
        run = _run()
        rankings, _ = _service()._calculate_rankings(
            run,
            [_snapshot(run, uuid4(), "10.00", reviews=0), _snapshot(run, uuid4(), "20.00", reviews=0)],
        )
        self.assertEqual([ranking.review_score for ranking in rankings], [Decimal("0.0000"), Decimal("0.0000")])

    def test_missing_rating_and_unknown_availability(self) -> None:
        run = _run()
        rankings, _ = _service()._calculate_rankings(
            run,
            [_snapshot(run, uuid4(), "10.00", rating=None, stock="UNKNOWN")],
        )
        self.assertEqual(rankings[0].rating_score, Decimal("0.0000"))
        self.assertEqual(rankings[0].availability_score, Decimal("50.0000"))

    def test_invalid_price_exclusion(self) -> None:
        run = _run()
        valid = _snapshot(run, uuid4(), "10.00")
        invalid = _snapshot(run, uuid4(), None)
        rankings, diagnostics = _service()._calculate_rankings(run, [valid, invalid])
        self.assertEqual(len(rankings), 1)
        self.assertEqual(diagnostics.excluded_records[0]["reason"], "missing_or_invalid_price")

    def test_weight_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "must total 100"):
            _service(
                RankingConfig(
                    RankingWeights(Decimal("35"), Decimal("30"), Decimal("20"), Decimal("10")),
                    "v1",
                )
            )

    def test_deterministic_tie_breaking(self) -> None:
        run = _run()
        first = uuid4()
        second = uuid4()
        ordered = sorted([first, second], key=str)
        rankings, _ = _service()._calculate_rankings(
            run,
            [
                _snapshot(run, second, "10.00", rating="4.00", reviews=5),
                _snapshot(run, first, "10.00", rating="4.00", reviews=5),
            ],
        )
        self.assertEqual([ranking.competitor_id for ranking in rankings], ordered)
        self.assertEqual([ranking.market_rank for ranking in rankings], [1, 2])

    def test_idempotent_retry(self) -> None:
        run = _run()
        repo = FakeRankingRepo(run, [_snapshot(run, uuid4(), "10.00")])
        service = _service(repo=repo)
        first = service.calculate_for_scrape_run(run.id)
        second = service.calculate_for_scrape_run(run.id)
        self.assertEqual(first.created_count, 1)
        self.assertEqual(second.created_count, 0)
        self.assertEqual(second.skipped_existing_count, 1)

    def test_formula_versioning_creates_new_history(self) -> None:
        run = _run()
        snapshot = _snapshot(run, uuid4(), "10.00")
        repo = FakeRankingRepo(run, [snapshot])
        service_v1 = _service(repo=repo, config=RankingConfig(_weights(), "v1"))
        service_v2 = _service(repo=repo, config=RankingConfig(_weights(), "v2"))
        self.assertEqual(service_v1.calculate_for_scrape_run(run.id).created_count, 1)
        self.assertEqual(service_v2.calculate_for_scrape_run(run.id).created_count, 1)
        self.assertEqual({ranking.formula_version for ranking in repo.items}, {"v1", "v2"})

    def test_seller_scope_is_persisted(self) -> None:
        seller_id = uuid4()
        run = _run(seller_id=seller_id)
        repo = FakeRankingRepo(run, [_snapshot(run, uuid4(), "10.00")])
        _service(repo=repo).calculate_for_scrape_run(run.id)
        self.assertEqual(repo.items[0].seller_id, seller_id)


def _service(config: RankingConfig | None = None, repo=None) -> CompetitorRankingService:
    service = CompetitorRankingService.__new__(CompetitorRankingService)
    service._db = FakeDb()
    service._config = config or RankingConfig(_weights(), "v1")
    service._config.validate()
    service._repo = repo or FakeRankingRepo(_run(), [])
    service._log = NullLog()
    return service


def _weights() -> RankingWeights:
    return RankingWeights(Decimal("35"), Decimal("30"), Decimal("20"), Decimal("15"))


def _run(*, seller_id=None) -> ScrapeRun:
    now = datetime(2026, 6, 29, 12, tzinfo=timezone.utc)
    return ScrapeRun(
        id=uuid4(),
        seller_id=seller_id or uuid4(),
        product_id=uuid4(),
        marketplace="Daraz Bangladesh",
        run_key=f"rank:{uuid4()}",
        status="COMPLETED",
        completed_at=now,
        finished_at=now,
        created_at=now,
    )


def _snapshot(
    run: ScrapeRun,
    competitor_id,
    price: str | None,
    *,
    rating: str | None = "5.00",
    reviews: int | None = 10,
    stock: str = "IN_STOCK",
) -> CompetitorSnapshot:
    return CompetitorSnapshot(
        id=uuid4(),
        scrape_run_id=run.id,
        competitor_id=competitor_id,
        product_id=run.product_id,
        price=Decimal(price) if price is not None else None,
        currency="BDT",
        rating=Decimal(rating) if rating is not None else None,
        review_count=reviews,
        stock_status=stock,
        captured_at=run.completed_at,
    )


class FakeDb:
    def commit(self):
        pass

    def rollback(self):
        pass


class FakeRankingRepo:
    def __init__(self, run, snapshots):
        self.run = run
        self.snapshots = snapshots
        self.items = []

    def get_completed_run(self, scrape_run_id):
        return self.run if self.run.id == scrape_run_id and self.run.status == "COMPLETED" else None

    def snapshots_for_run(self, scrape_run_id):
        return self.snapshots if self.run.id == scrape_run_id else []

    def existing_competitor_ids(self, *, scrape_run_id, formula_version):
        return {
            ranking.competitor_id
            for ranking in self.items
            if ranking.scrape_run_id == scrape_run_id and ranking.formula_version == formula_version
        }

    def add_all(self, rankings):
        self.items.extend(rankings)


class NullLog:
    def info(self, *args, **kwargs):
        pass


if __name__ == "__main__":
    unittest.main()
