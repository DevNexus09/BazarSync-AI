from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from celery.exceptions import Ignore
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.ai.prompts import validate_prompt_context
from app.api.v1 import recommendations
from app.core.config import settings
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.dependencies.events import get_dashboard_event_emitter
from app.models.competitor import Competitor
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.inventory_history import InventoryHistory
from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.pricing_policy import PricingPolicy
from app.models.rag_index_outbox import RagIndexOutbox
from app.models.recommendation import Recommendation
from app.models.recommendation_job import RecommendationJob, RecommendationJobRequest
from app.models.scrape_run import ScrapeRun
from app.models.sales_data_coverage import SalesDataCoverage
from app.models.sales_record import SalesRecord
from app.models.seller import Seller
from app.services.recommendation_evidence_service import (
    Freshness,
    RecommendationEvidenceService,
)
from app.services.recommendation_service import RecommendationService
from app.tasks import recommendation_tasks

MARKETPLACE = "Daraz Bangladesh"
PRICE = Decimal("500.00")


@pytest.fixture
def db(monkeypatch):
    url = os.environ.get("BAZARSYNC_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("set BAZARSYNC_TEST_POSTGRES_URL for disposable PostgreSQL checks")
    admin = create_engine(url)
    schema = f"recommendation_test_{uuid4().hex}"
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Product.metadata.create_all(
            engine,
            tables=[
                Seller.__table__,
                Product.__table__,
                ScrapeRun.__table__,
                Competitor.__table__,
                CompetitorSnapshot.__table__,
                PriceHistory.__table__,
                Recommendation.__table__,
                RecommendationJob.__table__,
                RecommendationJobRequest.__table__,
                RagIndexOutbox.__table__,
                InventoryHistory.__table__,
                MarketplaceFeePolicy.__table__,
                PricingPolicy.__table__,
                SalesDataCoverage.__table__,
                SalesRecord.__table__,
            ],
        )
        monkeypatch.setattr(settings, "recommendation_evidence_enabled", True)
        monkeypatch.setattr(settings, "recommendation_price_max_age_hours", 24)
        monkeypatch.setattr(settings, "recommendation_stock_max_age_hours", 6)
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


def _product(db) -> Product:
    with db.begin() as session:
        seller = Seller(email=f"{uuid4()}@example.test", password_hash="test")
        session.add(seller)
        session.flush()
        product = Product(
            seller_id=seller.id,
            title="Test product",
            cost_price=Decimal("200"),
            selling_price=PRICE,
            stock_quantity=100,
            supplier_lead_time=7,
            minimum_margin=Decimal("10"),
        )
        session.add(product)
    return product


def _run(
    session: Session, product: Product, captured: datetime, **updates
) -> ScrapeRun:
    fields = {
        "status": "COMPLETED",
        "started_at": captured - timedelta(minutes=5),
        "finished_at": captured + timedelta(seconds=1),
        "created_at": captured - timedelta(minutes=6),
    } | updates
    run = ScrapeRun(
        seller_id=product.seller_id,
        product_id=product.id,
        marketplace=MARKETPLACE,
        run_key=str(uuid4()),
        **fields,
    )
    session.add(run)
    session.flush()
    return run


def _snapshot(
    session: Session,
    run: ScrapeRun,
    captured: datetime,
    *,
    competitor: Competitor | None = None,
    **updates,
) -> CompetitorSnapshot:
    if competitor is None:
        competitor = Competitor(
            product_id=run.product_id,
            scrape_run_id=run.id,
            marketplace=MARKETPLACE,
            competitor_title="Competitor",
            competitor_price=PRICE,
            stock_status="in_stock",
        )
        session.add(competitor)
        session.flush()
    fields = {
        "price": PRICE,
        "stock_status": "IN_STOCK",
        "price_observed_at": captured - timedelta(minutes=2),
        "stock_observed_at": captured - timedelta(minutes=1),
    } | updates
    snapshot = CompetitorSnapshot(
        scrape_run_id=run.id,
        product_id=run.product_id,
        competitor_id=competitor.id,
        captured_at=captured,
        **fields,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _collect(session: Session, product: Product, **scope):
    return RecommendationEvidenceService(session).collect(
        seller_id=product.seller_id,
        product_id=product.id,
        **scope,
    )


@pytest.mark.parametrize(
    ("age_hours", "price_status", "stock_status"),
    [
        (1, Freshness.FRESH, Freshness.FRESH),
        (7, Freshness.FRESH, Freshness.STALE),
        (25, Freshness.STALE, Freshness.STALE),
    ],
)
def test_freshness_windows_and_snapshot_priority(
    db, age_hours, price_status, stock_status
):
    now = datetime.now(timezone.utc)
    capture = now - timedelta(hours=age_hours)
    product = _product(db)
    with db.begin() as session:
        run = _run(session, product, capture)
        snapshot = _snapshot(session, run, capture)
        competitor = session.get(Competitor, snapshot.competitor_id)
        competitor.competitor_price = Decimal("999")
        competitor.stock_status = "out_of_stock"
    with db() as session:
        evidence = _collect(session, product, now=now)
        (row,) = evidence.observations
        assert row.price_evidence.status == price_status
        assert row.stock_evidence.status == stock_status
        if price_status == Freshness.FRESH:
            (item,) = evidence.market_competitors
            assert item["price"] == 500
            assert item["stock_status"] == (
                "IN_STOCK" if stock_status == Freshness.FRESH else None
            )
        else:
            assert not evidence.market_competitors


@pytest.mark.parametrize(
    ("price", "price_time", "expected"),
    [
        (None, None, Freshness.MISSING),
        (PRICE, None, Freshness.UNKNOWN),
        (PRICE, 10, Freshness.CARRIED_FORWARD),
        (PRICE, -1, Freshness.INVALID),
        (Decimal("0"), 1, Freshness.INVALID),
    ],
)
def test_price_provenance_and_invalid_stock(db, price, price_time, expected):
    now = datetime.now(timezone.utc)
    capture = now - timedelta(minutes=5)
    with db.begin() as session:
        product = _product(db)
        run = _run(session, product, capture)
        snapshot = _snapshot(
            session,
            run,
            capture,
            price=price,
            stock_status="UNKNOWN",
            raw_stock_text="maybe",
            price_observed_at=None
            if price_time is None
            else capture - timedelta(minutes=price_time),
        )
        session.get(Competitor, snapshot.competitor_id).competitor_price = None
    with db() as session:
        evidence = _collect(session, product, now=now)
        (row,) = evidence.observations
        assert row.price_evidence.status == expected
        assert row.stock_evidence.status == Freshness.INVALID
        assert evidence.market_competitors == []
        assert len(evidence.to_context()["rejected_observations"]) == 2


def test_carried_price_and_prior_history_do_not_fill_snapshot(db):
    now = datetime.now(timezone.utc)
    capture = now - timedelta(minutes=5)
    product = _product(db)
    with db.begin() as session:
        old = _run(session, product, capture - timedelta(hours=1))
        old_snapshot = _snapshot(session, old, capture - timedelta(hours=1))
        current = _run(session, product, capture)
        competitor = session.get(Competitor, old_snapshot.competitor_id)
        competitor.scrape_run_id = current.id
        _snapshot(
            session,
            current,
            capture,
            competitor=competitor,
            price=None,
            price_observed_at=None,
        )
        session.add(
            PriceHistory(
                competitor_id=competitor.id,
                observed_price=PRICE,
                observed_at=old_snapshot.price_observed_at,
            )
        )
    with db.begin() as session:
        evidence = _collect(session, product, now=now)
        assert evidence.market_competitors == []
        assert (
            evidence.observations[0].price_evidence.status == Freshness.CARRIED_FORWARD
        )
        assert evidence.observations[0].price_evidence.observed_at is None
        session.get(Competitor, competitor.id).competitor_price = None
    with db() as session:
        evidence = _collect(session, product, now=now)
        assert evidence.observations[0].price_evidence.status == Freshness.HISTORICAL
        assert evidence.market_competitors == []
        assert (
            _collect(
                session, product, now=now, scrape_run_id=old.id
            ).market_competitors[0]["price"]
            == 500
        )
        assert session.get(CompetitorSnapshot, old_snapshot.id).price == PRICE


def test_run_scope_and_empty_completed_run(db):
    now = datetime.now(timezone.utc)
    product = _product(db)
    other_product = _product(db)
    with db.begin() as session:
        old = _run(session, product, now - timedelta(hours=1))
        _snapshot(session, old, now - timedelta(hours=1))
        current = _run(
            session, product, now - timedelta(minutes=5), successful_matches=0
        )
        active = _run(session, product, now - timedelta(minutes=2), status="RUNNING")
        foreign = _run(session, other_product, now - timedelta(minutes=2))
        alien = _snapshot(session, foreign, now - timedelta(minutes=2))
        _snapshot(
            session,
            old,
            now - timedelta(hours=1),
            competitor=session.get(Competitor, alien.competitor_id),
        )
    with db() as session:
        service = RecommendationEvidenceService(session)
        evidence = _collect(session, product, now=now)
        assert evidence.scrape_run_id == current.id
        assert evidence.quality_flags == ("NO_MATCHES",)
        assert (
            len(_collect(session, product, now=now, scrape_run_id=old.id).observations)
            == 1
        )
        for run_id in (active.id, foreign.id):
            assert (
                _collect(session, product, now=now, scrape_run_id=run_id).scrape_run_id
                is None
            )
        cross_seller = service.collect(
            seller_id=other_product.seller_id, product_id=product.id, now=now
        )
        assert cross_seller.quality_flags == ("NO_COMPLETED_SCRAPE",)
        assert cross_seller.observations == ()


def test_configured_limits_and_disabled_compatibility_path(db, monkeypatch):
    now = datetime.now(timezone.utc)
    capture = now - timedelta(hours=2)
    product = _product(db)
    with db.begin() as session:
        run = _run(session, product, capture)
        _snapshot(session, run, capture)
    monkeypatch.setattr(settings, "recommendation_price_max_age_hours", 1)
    monkeypatch.setattr(settings, "recommendation_stock_max_age_hours", 3)
    with db() as session:
        evidence = _collect(session, product, now=now)
        assert evidence.observations[0].price_evidence.status == Freshness.STALE
        assert evidence.observations[0].stock_evidence.status == Freshness.FRESH
        monkeypatch.setattr(settings, "recommendation_evidence_enabled", False)
        service = RecommendationService(session)
        monkeypatch.setattr(service, "_apply_margin_guard", Mock())
        context, _, evidence = service.prepare_recommendation(product)
        assert evidence is None
        assert context["competitor_median_price"] == 500
        assert context["competitors_oos"] == 0


def test_api_queues_verified_run_and_worker_persists_evidence(db, monkeypatch):
    now = datetime.now(timezone.utc)
    capture = now - timedelta(minutes=10)
    product = _product(db)
    foreign_product = _product(db)
    with db.begin() as session:
        run = _run(session, product, capture)
        _snapshot(session, run, capture, stock_observed_at=None)
        old = Recommendation(
            product_id=product.id,
            action="HOLD",
            confidence="LOW",
            reasoning_bn="আগের পরামর্শ",
            recommendation_context={"competitor_median_price": 450},
            created_at=capture,
        )
        session.add(old)
    app = FastAPI()
    app.include_router(recommendations.router)

    def get_test_session():
        with db() as session:
            yield session

    app.dependency_overrides[get_db] = get_test_session
    authenticated = SimpleNamespace(id=product.seller_id)
    app.dependency_overrides[get_current_seller] = lambda: authenticated
    app.dependency_overrides[get_dashboard_event_emitter] = lambda: Mock()
    send = Mock(return_value=SimpleNamespace(id="task-123"))
    monkeypatch.setattr(recommendations.celery_app, "send_task", send)
    monkeypatch.setattr(recommendation_tasks, "SessionLocal", db)
    guard = Mock()
    guard.validate_candidate.return_value = SimpleNamespace(
        candidate_price=PRICE,
        is_allowed=True,
        to_evidence=lambda: {},
    )
    monkeypatch.setattr(
        "app.services.recommendation_service.MarginGuard", Mock(return_value=guard)
    )

    async def explain(_self, context):
        assert context["competitors_oos"] is None
        assert validate_prompt_context(context).competitors_oos is None
        assert context["days_of_stock_left"] == 100
        return SimpleNamespace(
            recommendation=SimpleNamespace(
                action="HOLD",
                confidence="HIGH",
                reasoning_bn="দাম অপরিবর্তিত রাখুন",
                revenue_opportunity=0,
            ),
            metadata=SimpleNamespace(model="test", latency_ms=0, retry_count=0),
        )

    monkeypatch.setattr(RecommendationService, "generate_ai_recommendation", explain)
    monkeypatch.setattr(
        RecommendationService, "_emit_recommendation_created", AsyncMock()
    )
    with TestClient(app) as client:
        authenticated.id = foreign_product.seller_id
        forbidden = client.post(f"/recommendations/generate/{product.id}")
        assert forbidden.status_code == 404
        assert forbidden.json()["error_code"] == "product_not_found"
        send.assert_not_called()
        authenticated.id = product.seller_id
        queued = client.post(f"/recommendations/generate/{product.id}")
        assert queued.status_code == 202
        assert queued.json() == {
            "success": True,
            "status": "processing",
            "product_id": str(product.id),
            "task_id": "task-123",
        }
        send.assert_called_once_with(
            "analytics.generate_ai_recommendation",
            args=[str(product.id), str(product.seller_id)],
            kwargs={"scrape_run_id": str(run.id)},
        )
        with db.begin() as session:
            _run(session, product, now - timedelta(minutes=2), successful_matches=0)
        unavailable = client.post(f"/recommendations/generate/{product.id}")
        assert unavailable.status_code == 404
        assert unavailable.json()["error_code"] == "competitor_data_missing"
        recommendation_tasks.generate_ai_recommendation_task.run(
            *send.call_args.kwargs["args"],
            **send.call_args.kwargs["kwargs"],
        )
        latest = client.get(f"/recommendations/latest/{product.id}")
        assert latest.status_code == 200
        assert latest.json()["analytics"]["competitor_median_price"] == 500
        assert latest.json()["analytics"]["competitors_oos"] is None
    with db() as session:
        records = session.scalars(
            select(Recommendation).order_by(Recommendation.created_at)
        ).all()
        assert len(records) == 2
        assert records[0].recommendation_context == {"competitor_median_price": 450}
        evidence = records[1].recommendation_context["competitor_evidence"]
        assert evidence["scrape_run_id"] == str(run.id)
        assert evidence["freshness_status"] == "PARTIAL"
        assert evidence["missing_fields"] == ["stock_status"]
        assert evidence["competitor_coverage"]["fresh_prices"] == 1
        assert session.scalar(select(RagIndexOutbox)).source_id == str(records[1].id)


def test_worker_rechecks_pinned_run_freshness(db, monkeypatch):
    product = _product(db)
    captured = datetime.now(timezone.utc) - timedelta(hours=2)
    with db.begin() as session:
        pinned = _run(session, product, captured)
        _snapshot(session, pinned, captured)
        assert _collect(session, product).market_competitors
        newer_capture = datetime.now(timezone.utc) - timedelta(minutes=5)
        newer = _run(session, product, newer_capture)
        _snapshot(session, newer, newer_capture)
    monkeypatch.setattr(settings, "recommendation_price_max_age_hours", 1)
    monkeypatch.setattr(recommendation_tasks, "SessionLocal", db)
    explain = AsyncMock()
    monkeypatch.setattr(RecommendationService, "generate_ai_recommendation", explain)
    with pytest.raises(Ignore):
        recommendation_tasks.generate_ai_recommendation_task.run(
            str(product.id),
            str(product.seller_id),
            scrape_run_id=str(pinned.id),
        )
    explain.assert_not_called()
    with db() as session:
        assert session.scalar(select(Recommendation)) is None


@pytest.mark.parametrize("validation_enabled", [False, True])
def test_business_signals_worker_uses_recorded_sales_and_effective_product_fees(
    db, monkeypatch, validation_enabled
):
    now = datetime.now(timezone.utc)
    product = _product(db)
    capture = now - timedelta(minutes=5)
    monkeypatch.setattr(settings, "recommendation_business_signals_enabled", True)
    monkeypatch.setattr(settings, "recommendation_validation_enabled", validation_enabled)
    monkeypatch.setattr(settings, "sales_velocity_default_window_days", 30)
    monkeypatch.setattr(recommendation_tasks, "SessionLocal", db)
    explain = AsyncMock()
    monkeypatch.setattr(RecommendationService, "generate_ai_recommendation", explain)
    monkeypatch.setattr(
        RecommendationService, "_emit_recommendation_created", AsyncMock()
    )
    with db.begin() as session:
        owned = session.get(Product, product.id)
        owned.created_at = now - timedelta(days=60)
        through = now.date() - timedelta(days=1)
        run = _run(session, product, capture)
        _snapshot(session, run, capture, price=Decimal("450.02"), match_score=0.95)
        _snapshot(session, run, capture, price=Decimal("450.05"), match_score=0.96)
        if validation_enabled:
            _snapshot(session, run, capture, price=Decimal("1.00"), match_score=0.4)
        session.add(
            SalesDataCoverage(
                seller_id=product.seller_id,
                product_id=product.id,
                marketplace=MARKETPLACE,
                source="test",
                coverage_start_date=through - timedelta(days=29),
                coverage_end_date=through,
                completeness_status="COMPLETE",
                last_imported_at=now,
            )
        )
        for day in range(1, 11):
            session.add(
                SalesRecord(
                    seller_id=product.seller_id,
                    product_id=product.id,
                    sold_at=datetime.combine(
                        now.date() - timedelta(days=day),
                        datetime.min.time(),
                        tzinfo=timezone.utc,
                    ),
                    quantity_sold=4,
                    returned_units=1,
                    status="COMPLETED",
                )
            )
        session.add(
            SalesRecord(
                seller_id=product.seller_id,
                product_id=product.id,
                sold_at=now - timedelta(days=2),
                quantity_sold=80,
                status="CANCELLED",
            )
        )
        session.add(
            SalesRecord(
                seller_id=product.seller_id,
                product_id=product.id,
                sold_at=now - timedelta(days=2),
                quantity_sold=1,
                returned_units=2,
                status="FULFILLED",
            )
        )
        session.add(
            InventoryHistory(
                seller_id=product.seller_id,
                product_id=product.id,
                snapshot_date=now.date(),
                captured_at=capture,
                quantity_on_hand=100,
                quantity_reserved=10,
                quantity_available=90,
                source="DAILY_SNAPSHOT",
                content_hash="test",
            )
        )
        session.add(
            PricingPolicy(
                seller_id=product.seller_id,
                product_id=product.id,
                marketplace=MARKETPLACE,
                minimum_margin_rate=Decimal("0.10"),
                price_increment=Decimal("0.05"),
                effective_from=now - timedelta(days=1),
            )
        )
        session.add_all(
            [
                MarketplaceFeePolicy(
                    seller_id=product.seller_id,
                    marketplace=MARKETPLACE,
                    version="seller",
                    percentage_commission_rate=Decimal("0.70"),
                    effective_from=now - timedelta(days=1),
                ),
                MarketplaceFeePolicy(
                    seller_id=product.seller_id,
                    product_id=product.id,
                    marketplace=MARKETPLACE,
                    version="product",
                    percentage_commission_rate=Decimal("0.10"),
                    effective_from=now - timedelta(days=1),
                ),
            ]
        )

    recommendation_tasks.generate_ai_recommendation_task.run(
        str(product.id),
        str(product.seller_id),
        scrape_run_id=str(run.id),
    )
    explain.assert_not_called()
    with db() as session:
        saved = session.scalar(select(Recommendation))
        assert saved.action.value == "LOWER"
        assert (
            saved.suggested_price_min == saved.suggested_price_max == Decimal("450.00")
        )
        assert saved.revenue_opportunity == 0
        assert (
            saved.recommendation_context["margin_guard"]["policy_version"] == "product"
        )
        inventory = saved.recommendation_context["analytics"]["inventory_evidence"]
        assert inventory["demand_status"] == "OBSERVED"
        assert inventory["daily_net_sales_rate"] == "1.0000"
        assert inventory["recorded_net_units"] == 30
        assert inventory["recorded_returns"] == 12
        latest = RecommendationService(session).get_latest_recommendation(
            product_id=product.id,
            seller_id=product.seller_id,
        )
        assert latest.analytics.stock_coverage_available is True
        assert latest.analytics.estimated_days_of_stock_left == 90
        if validation_enabled:
            assessment = saved.recommendation_context["evidence_assessment"]
            assert assessment["confidence"] == saved.confidence.value == "MEDIUM"
            assert assessment["data_completeness"]["eligible_price_count"] == 2
            assert assessment["predictive_uncertainty"] is None
            assert latest.analytics.competitor_median_price == 450.035
