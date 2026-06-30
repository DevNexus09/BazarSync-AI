from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from uuid import UUID, uuid4

from app.models.competitor_event import CompetitorEventType
from app.models.competitor_ranking import CompetitorRanking
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.product import Product
from app.models.scrape_run import ScrapeRun
from app.services.competitor_event_service import CompetitorEventConfig, CompetitorEventService
from app.services.competitor_ranking_service import CompetitorRankingService, RankingConfig, RankingWeights
from app.services.market_opportunity_service import (
    MarketOpportunityConfig,
    MarketOpportunityService,
    MarketOpportunityWeights,
)
from app.websocket.socket_events import RealtimeEventType


class Phase5AcceptanceWorkflowTest(unittest.TestCase):
    def test_complete_fixture_workflow(self) -> None:
        fixture = Phase5Fixture()
        pipeline = Phase5Pipeline(fixture)

        run1 = fixture.add_run(
            index=1,
            competitors={
                "A": ("320", "IN_STOCK", "4.5", 900),
                "B": ("500", "IN_STOCK", "4.7", 1500),
                "C": ("450", "IN_STOCK", "4.0", 400),
            },
        )
        result1 = pipeline.process(run1)
        self.assertEqual(result1["events"], 0)
        self.assertEqual(result1["rankings"], 3)
        self.assertEqual(result1["opportunities"], 0)

        run2 = fixture.add_run(
            index=2,
            competitors={
                "A": ("290", "IN_STOCK", None, None),
                "B": ("550", "OUT_OF_STOCK", None, None),
                "D": ("400", "IN_STOCK", None, None),
            },
        )
        result2 = pipeline.process(run2)
        run2_events = fixture.events_for_run(run2.id)
        self.assertCountEqual(
            [event.event_type for event in run2_events],
            [
                CompetitorEventType.PRICE_DROP,
                CompetitorEventType.PRICE_RISE,
                CompetitorEventType.OUT_OF_STOCK,
                CompetitorEventType.NEW_COMPETITOR,
            ],
        )
        self.assertFalse(
            any(event.event_type == CompetitorEventType.COMPETITOR_REMOVED for event in run2_events)
        )
        self.assertGreater(result2["rankings"], 0)
        self.assertEqual(result2["opportunities"], 2)
        self.assertEqual(len(fixture.published), 10)

        run3 = fixture.add_run(
            index=3,
            competitors={
                "A": ("290", "IN_STOCK", None, None),
                "B": ("550", "OUT_OF_STOCK", None, None),
                "D": ("400", "IN_STOCK", None, None),
            },
        )
        result3 = pipeline.process(run3)
        run3_events = fixture.events_for_run(run3.id)
        self.assertEqual(
            [event.event_type for event in run3_events],
            [CompetitorEventType.COMPETITOR_REMOVED],
        )
        self.assertEqual(run3_events[0].competitor_id, fixture.competitor_ids["C"])
        self.assertEqual(result3["opportunities"], 1)

        retry_result = pipeline.process(run3)
        self.assertEqual(retry_result["events"], 0)
        self.assertEqual(retry_result["opportunities"], 0)
        self.assertEqual(
            sum(
                1
                for event in fixture.events
                if event.event_type == CompetitorEventType.COMPETITOR_REMOVED
                and event.competitor_id == fixture.competitor_ids["C"]
            ),
            1,
        )

        run4 = fixture.add_run(index=4, competitors={}, status="PARTIAL")
        result4 = pipeline.process(run4)
        self.assertEqual(result4["skipped_reason"], "not_completed")
        self.assertEqual(fixture.events_for_run(run4.id), [])
        self.assertEqual(fixture.opportunities_for_run(run4.id), [])
        self.assertEqual(fixture.summary()["competitor_count"], 3)

        other_seller_summary = fixture.summary(seller_id=uuid4())
        self.assertEqual(other_seller_summary["competitor_count"], 0)
        self.assertEqual(other_seller_summary["open_opportunity_count"], 0)


class Phase5Pipeline:
    def __init__(self, fixture: "Phase5Fixture") -> None:
        self.fixture = fixture

    def process(self, scrape_run: ScrapeRun) -> dict:
        if scrape_run.status != "COMPLETED":
            return {"skipped_reason": "not_completed", "events": 0, "rankings": 0, "opportunities": 0}

        event_service = CompetitorEventService.__new__(CompetitorEventService)
        event_service._db = FakeDb()
        event_service._config = CompetitorEventConfig(Decimal("1.00"), Decimal("1.00"), 2)
        event_service._events = self.fixture
        event_service._snapshots = self.fixture
        event_service._log = NullLog()
        event_result = event_service.generate_for_scrape_run(scrape_run.id)

        ranking_service = CompetitorRankingService.__new__(CompetitorRankingService)
        ranking_service._db = FakeDb()
        ranking_service._config = RankingConfig(
            RankingWeights(Decimal("35"), Decimal("30"), Decimal("20"), Decimal("15")),
            "v1",
        )
        ranking_service._repo = self.fixture
        ranking_service._log = NullLog()
        ranking_result = ranking_service.calculate_for_scrape_run(scrape_run.id)

        opportunity_service = MarketOpportunityService.__new__(MarketOpportunityService)
        opportunity_service._db = FakeDb()
        opportunity_service._config = MarketOpportunityConfig(
            MarketOpportunityWeights(Decimal("30"), Decimal("25"), Decimal("20"), Decimal("15"), Decimal("10")),
            Decimal("75"),
            Decimal("45"),
            14,
            "v1",
            "v1",
        )
        opportunity_service._repo = self.fixture
        opportunity_service._log = NullLog()
        opportunity_result = opportunity_service.generate_for_scrape_run(scrape_run.id)

        self.fixture.publish(scrape_run)
        return {
            "events": event_result.generated_count,
            "rankings": ranking_result.created_count,
            "opportunities": opportunity_result.created_count,
        }


class Phase5Fixture:
    def __init__(self) -> None:
        self.seller_id = uuid4()
        self.product_id = uuid4()
        self.product_obj = Product(
            id=self.product_id,
            seller_id=self.seller_id,
            title="Seller Product",
            description="",
            category="Beauty",
            specifications={"marketplace_fee": "0.05"},
            cost_price=Decimal("220"),
            selling_price=Decimal("350"),
            stock_quantity=50,
            supplier_lead_time=5,
            minimum_margin=Decimal("20"),
        )
        self.runs: dict[UUID, ScrapeRun] = {}
        self.snapshots: dict[UUID, dict[UUID, CompetitorSnapshot]] = {}
        self.competitor_ids = {label: uuid4() for label in ["A", "B", "C", "D"]}
        self.events = []
        self.rankings: list[CompetitorRanking] = []
        self.opportunities = []
        self.published: list[tuple[RealtimeEventType, UUID]] = []

    def add_run(self, *, index: int, competitors: dict[str, tuple], status: str = "COMPLETED") -> ScrapeRun:
        timestamp = datetime(2026, 6, 29, 12, tzinfo=timezone.utc) + timedelta(hours=index)
        run = ScrapeRun(
            id=uuid4(),
            seller_id=self.seller_id,
            product_id=self.product_id,
            marketplace="Daraz Bangladesh",
            run_key=f"fixture:{index}",
            status=status,
            created_at=timestamp,
            completed_at=timestamp if status == "COMPLETED" else None,
            finished_at=timestamp,
            snapshot_count=len(competitors),
        )
        self.runs[run.id] = run
        self.snapshots[run.id] = {
            self.competitor_ids[label]: self._snapshot(run, label, *values)
            for label, values in competitors.items()
        }
        return run

    def _snapshot(
        self,
        run: ScrapeRun,
        label: str,
        price: str,
        stock_status: str,
        rating: str | None,
        reviews: int | None,
    ) -> CompetitorSnapshot:
        return CompetitorSnapshot(
            id=uuid4(),
            scrape_run_id=run.id,
            competitor_id=self.competitor_ids[label],
            product_id=run.product_id,
            price=Decimal(price),
            currency="BDT",
            rating=Decimal(rating) if rating is not None else None,
            review_count=reviews,
            stock_status=stock_status,
            captured_at=run.completed_at or run.finished_at,
        )

    def publish(self, run: ScrapeRun) -> None:
        for event in (
            RealtimeEventType.COMPETITOR_SNAPSHOT_CREATED,
            RealtimeEventType.COMPETITOR_EVENT_CREATED,
            RealtimeEventType.COMPETITOR_RANKINGS_UPDATED,
            RealtimeEventType.MARKET_OPPORTUNITY_CREATED,
            RealtimeEventType.COMPETITOR_SUMMARY_UPDATED,
        ):
            self.published.append((event, run.id))

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

    def snapshots_for_run(self, scrape_run_id):
        return list(self.snapshots.get(scrape_run_id, {}).values())

    def historical_competitor_ids_before(self, current_run):
        competitor_ids = set()
        for run in self.runs.values():
            if run.status == "COMPLETED" and run.created_at < current_run.created_at:
                competitor_ids.update(self.snapshots.get(run.id, {}))
        return competitor_ids

    def existing_dedupe_keys(self, keys):
        existing = {event.dedupe_key for event in self.events}
        return existing & set(keys)

    def has_removal_event(self, *, product_id, competitor_id):
        return any(
            event.product_id == product_id
            and event.competitor_id == competitor_id
            and event.event_type == CompetitorEventType.COMPETITOR_REMOVED
            for event in self.events
        )

    def add_all(self, items):
        if not items:
            return
        for item in items:
            if getattr(item, "id", None) is None:
                item.id = uuid4()
        first = items[0]
        if isinstance(first, CompetitorRanking):
            self.rankings.extend(items)
        elif hasattr(first, "trigger_event_id"):
            self.opportunities.extend(items)
        else:
            self.events.extend(items)

    def existing_competitor_ids(self, *, scrape_run_id, formula_version):
        return {
            ranking.competitor_id
            for ranking in self.rankings
            if ranking.scrape_run_id == scrape_run_id and ranking.formula_version == formula_version
        }

    def product(self, product_id):
        return self.product_obj if product_id == self.product_id else None

    def trigger_events_for_run(self, scrape_run_id):
        return [
            event for event in self.events
            if event.scrape_run_id == scrape_run_id
            and event.event_type in {
                CompetitorEventType.OUT_OF_STOCK,
                CompetitorEventType.PRICE_RISE,
                CompetitorEventType.COMPETITOR_REMOVED,
            }
        ]

    def rankings_for_run(self, scrape_run_id, formula_version):
        return {
            ranking.competitor_id: ranking
            for ranking in self.rankings
            if ranking.scrape_run_id == scrape_run_id and ranking.formula_version == formula_version
        }

    def existing_trigger_ids(self, trigger_event_ids):
        return {
            opportunity.trigger_event_id
            for opportunity in self.opportunities
            if opportunity.trigger_event_id in trigger_event_ids
        }

    def events_for_run(self, scrape_run_id):
        return [event for event in self.events if event.scrape_run_id == scrape_run_id]

    def opportunities_for_run(self, scrape_run_id):
        return [item for item in self.opportunities if item.scrape_run_id == scrape_run_id]

    def summary(self, seller_id=None):
        seller_id = seller_id or self.seller_id
        completed_runs = [
            run for run in self.runs.values()
            if run.seller_id == seller_id and run.status == "COMPLETED"
        ]
        latest = max(completed_runs, key=lambda run: run.created_at, default=None)
        return {
            "competitor_count": len(self.snapshots.get(latest.id, {})) if latest else 0,
            "open_opportunity_count": len(
                [item for item in self.opportunities if item.seller_id == seller_id and item.status == "OPEN"]
            ),
        }


class FakeDb:
    def commit(self):
        pass

    def rollback(self):
        pass


class NullLog:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


if __name__ == "__main__":
    unittest.main()
