from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest
from uuid import uuid4

from app.models.competitor_event import CompetitorEvent, CompetitorEventType
from app.models.competitor_ranking import CompetitorRanking
from app.models.market_opportunity import MarketOpportunityAction, MarketOpportunityStatus
from app.models.product import Product
from app.models.scrape_run import ScrapeRun
from app.services.market_opportunity_service import (
    MarketOpportunityConfig,
    MarketOpportunityService,
    MarketOpportunityWeights,
)


class MarketOpportunityServiceTest(unittest.TestCase):
    def test_strong_competitor_stockout(self) -> None:
        run, product = _run_product(stock=27)
        event = _event(run, CompetitorEventType.OUT_OF_STOCK)
        ranking = _ranking(run, event.competitor_id, Decimal("91.4"), 1)
        service, repo = _service(run, product, [event], {event.competitor_id: ranking})
        result = service.generate_for_scrape_run(run.id)
        self.assertEqual(result.created_count, 1)
        opportunity = repo.items[0]
        self.assertEqual(opportunity.opportunity_level, "HIGH")
        self.assertEqual(opportunity.recommended_action, MarketOpportunityAction.HOLD)
        self.assertIn("competitor_total_score", opportunity.evidence)

    def test_weak_competitor_stockout_scores_lower(self) -> None:
        run, product = _run_product(stock=27)
        event = _event(run, CompetitorEventType.OUT_OF_STOCK)
        ranking = _ranking(run, event.competitor_id, Decimal("10"), 10)
        service, repo = _service(run, product, [event], {event.competitor_id: ranking})
        service.generate_for_scrape_run(run.id)
        self.assertLess(repo.items[0].opportunity_score, Decimal("75"))

    def test_price_rise_opportunity(self) -> None:
        run, product = _run_product(stock=20)
        event = _event(run, CompetitorEventType.PRICE_RISE, percent=Decimal("20"))
        service, repo = _service(run, product, [event], {event.competitor_id: _ranking(run, event.competitor_id, Decimal("80"), 2)})
        service.generate_for_scrape_run(run.id)
        self.assertEqual(repo.items[0].opportunity_type, "COMPETITOR_PRICE_RISE")

    def test_competitor_removal(self) -> None:
        run, product = _run_product(stock=20)
        event = _event(run, CompetitorEventType.COMPETITOR_REMOVED)
        service, repo = _service(run, product, [event], {})
        service.generate_for_scrape_run(run.id)
        self.assertEqual(repo.items[0].opportunity_type, "COMPETITOR_REMOVED")

    def test_seller_out_of_stock_and_low_stock_reorder(self) -> None:
        for stock in (0, 3):
            run, product = _run_product(stock=stock)
            event = _event(run, CompetitorEventType.OUT_OF_STOCK)
            service, repo = _service(run, product, [event], {event.competitor_id: _ranking(run, event.competitor_id, Decimal("90"), 1)})
            service.generate_for_scrape_run(run.id)
            self.assertEqual(repo.items[0].recommended_action, MarketOpportunityAction.REORDER)

    def test_margin_and_missing_fee_rules_are_conservative(self) -> None:
        run, product = _run_product(stock=10, selling=Decimal("101"), cost=Decimal("100"), margin=Decimal("5"))
        event = _event(run, CompetitorEventType.PRICE_RISE)
        service, repo = _service(run, product, [event], {event.competitor_id: _ranking(run, event.competitor_id, Decimal("90"), 1)})
        service.generate_for_scrape_run(run.id)
        self.assertEqual(repo.items[0].recommended_action, MarketOpportunityAction.HOLD)
        self.assertIn("marketplace_fee_missing", repo.items[0].evidence["confidence_penalties"])

    def test_missing_sales_history_sets_revenue_null(self) -> None:
        run, product = _run_product(stock=10)
        event = _event(run, CompetitorEventType.OUT_OF_STOCK)
        service, repo = _service(run, product, [event], {event.competitor_id: _ranking(run, event.competitor_id, Decimal("90"), 1)})
        service.generate_for_scrape_run(run.id)
        self.assertIsNone(repo.items[0].estimated_revenue)
        self.assertEqual(repo.items[0].evidence["revenue_estimate"]["reason"], "historical_sales_data_insufficient")

    def test_revenue_estimate_with_sufficient_data(self) -> None:
        _run, product = _run_product(stock=10, selling=Decimal("100"))
        service, _repo = _service(_run, product, [], {})
        revenue, evidence = service._estimate_revenue(
            product=product,
            opportunity_score=Decimal("80"),
            competitor_strength=Decimal("90"),
            event_type=CompetitorEventType.OUT_OF_STOCK,
            baseline_daily_units=Decimal("5"),
        )
        self.assertEqual(revenue, Decimal("1330.00"))
        self.assertTrue(evidence["available"])

    def test_duplicate_retry(self) -> None:
        run, product = _run_product(stock=20)
        event = _event(run, CompetitorEventType.OUT_OF_STOCK)
        service, repo = _service(run, product, [event], {event.competitor_id: _ranking(run, event.competitor_id, Decimal("90"), 1)})
        self.assertEqual(service.generate_for_scrape_run(run.id).created_count, 1)
        self.assertEqual(service.generate_for_scrape_run(run.id).created_count, 0)
        self.assertEqual(len(repo.items), 1)

    def test_acknowledge_and_dismiss(self) -> None:
        run, product = _run_product(stock=20)
        event = _event(run, CompetitorEventType.OUT_OF_STOCK)
        service, repo = _service(run, product, [event], {event.competitor_id: _ranking(run, event.competitor_id, Decimal("90"), 1)})
        service.generate_for_scrape_run(run.id)
        opportunity_id = repo.items[0].id
        self.assertEqual(service.acknowledge(seller_id=run.seller_id, opportunity_id=opportunity_id).status, MarketOpportunityStatus.ACKNOWLEDGED)
        self.assertEqual(service.dismiss(seller_id=run.seller_id, opportunity_id=opportunity_id).status, MarketOpportunityStatus.DISMISSED)

    def test_weight_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "must total 100"):
            MarketOpportunityConfig(
                MarketOpportunityWeights(Decimal("30"), Decimal("25"), Decimal("20"), Decimal("15"), Decimal("9")),
                Decimal("75"),
                Decimal("45"),
                14,
                "v1",
                "v1",
            ).validate()


def _service(run, product, events, rankings):
    service = MarketOpportunityService.__new__(MarketOpportunityService)
    service._db = FakeDb()
    service._config = MarketOpportunityConfig(
        MarketOpportunityWeights(Decimal("30"), Decimal("25"), Decimal("20"), Decimal("15"), Decimal("10")),
        Decimal("75"),
        Decimal("45"),
        14,
        "v1",
        "v1",
    )
    service._config.validate()
    service._repo = FakeRepo(run, product, events, rankings)
    service._log = NullLog()
    return service, service._repo


def _run_product(*, stock: int, selling=Decimal("315"), cost=Decimal("250"), margin=Decimal("20")):
    run = ScrapeRun(
        id=uuid4(),
        seller_id=uuid4(),
        product_id=uuid4(),
        marketplace="Daraz Bangladesh",
        run_key=f"opp:{uuid4()}",
        status="COMPLETED",
        completed_at=datetime(2026, 6, 29, 12, tzinfo=timezone.utc),
        created_at=datetime(2026, 6, 29, 12, tzinfo=timezone.utc),
    )
    product = Product(
        id=run.product_id,
        seller_id=run.seller_id,
        title="Seller Product",
        cost_price=cost,
        selling_price=selling,
        stock_quantity=stock,
        supplier_lead_time=5,
        minimum_margin=margin,
        specifications={},
    )
    return run, product


def _event(run, event_type, percent=Decimal("0")):
    return CompetitorEvent(
        id=uuid4(),
        seller_id=run.seller_id,
        product_id=run.product_id,
        competitor_id=uuid4(),
        scrape_run_id=run.id,
        event_type=event_type,
        price_change_percent=percent,
        severity="HIGH",
        dedupe_key=f"event:{uuid4()}",
        detected_at=run.completed_at,
    )


def _ranking(run, competitor_id, score, rank):
    return CompetitorRanking(
        id=uuid4(),
        seller_id=run.seller_id,
        product_id=run.product_id,
        competitor_id=competitor_id,
        scrape_run_id=run.id,
        price_score=score,
        rating_score=score,
        review_score=score,
        availability_score=score,
        total_score=score,
        market_rank=rank,
        formula_version="v1",
        calculated_at=run.completed_at,
    )


class FakeDb:
    def commit(self):
        pass

    def rollback(self):
        pass

    def refresh(self, _):
        pass


class FakeRepo:
    def __init__(self, run, product, events, rankings):
        self.run = run
        self.product_obj = product
        self.events = events
        self.rankings = rankings
        self.items = []

    def get_completed_run(self, scrape_run_id):
        return self.run if self.run.id == scrape_run_id else None

    def product(self, product_id):
        return self.product_obj if self.product_obj.id == product_id else None

    def trigger_events_for_run(self, scrape_run_id):
        return self.events if self.run.id == scrape_run_id else []

    def rankings_for_run(self, scrape_run_id, formula_version):
        return self.rankings

    def existing_trigger_ids(self, trigger_event_ids):
        return {item.trigger_event_id for item in self.items if item.trigger_event_id in trigger_event_ids}

    def add_all(self, opportunities):
        self.items.extend(opportunities)

    def get_for_seller(self, *, seller_id, opportunity_id):
        for item in self.items:
            if item.id == opportunity_id and item.seller_id == seller_id:
                return item
        return None

    def list_opportunities(self, **_):
        return self.items, len(self.items)


class NullLog:
    def info(self, *args, **kwargs):
        pass


if __name__ == "__main__":
    unittest.main()
