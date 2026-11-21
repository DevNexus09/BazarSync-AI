from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, update

from app.api.v1 import recommendations
from app.core.config import settings
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.dependencies.events import get_dashboard_event_emitter
from app.models.dead_stock_assessment import DeadStockAssessment
from app.models.dead_stock_recovery_recommendation import (
    DeadStockRecoveryRecommendation,
)
from app.models.demand_elasticity_estimate import DemandElasticityEstimate
from app.models.dynamic_pricing_recommendation import DynamicPricingRecommendation
from app.models.inventory_aging import InventoryAgingSnapshot
from app.models.inventory_history import InventoryHistory
from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.pricing_analytics_snapshot import PricingAnalyticsSnapshot
from app.models.product import Product
from app.models.product_visibility_metric import ProductVisibilityMetric
from app.models.rag_index_outbox import RagIndexOutbox
from app.models.recommendation import Recommendation, RecommendationAction
from app.models.reorder_recommendation import ReorderRecommendation
from app.models.sales_data_coverage import SalesDataCoverage
from app.models.sales_record import SalesRecord
from app.models.sales_velocity import SalesVelocity
from app.models.stockout_prediction import StockoutPrediction
from app.schemas.recommendation_candidate import (
    CandidateStatus,
    RecommendationCandidate,
)
from app.schemas.recommendation_decision import (
    DecisionInventory,
    RecommendationDecisionContext,
)
from app.services.decision_orchestrator import DecisionOrchestrator
from app.services.recommendation_service import RecommendationService
from app.services.recommendation_selection import EngineEvaluation, select_decision
from app.services.sales_velocity_service import SalesVelocityService
from app.tasks import recommendation_tasks
from test_recommendation_evidence import (
    MARKETPLACE,
    _collect,
    _product,
    _run,
    _snapshot,
)

pytest_plugins = ("test_recommendation_evidence",)


@pytest.fixture
def decision_db(db, monkeypatch):
    with db() as session:
        Product.metadata.create_all(
            session.get_bind(),
            tables=[
                DemandElasticityEstimate.__table__,
                InventoryAgingSnapshot.__table__,
                SalesVelocity.__table__,
                DeadStockAssessment.__table__,
                ProductVisibilityMetric.__table__,
                StockoutPrediction.__table__,
                PricingAnalyticsSnapshot.__table__,
                ReorderRecommendation.__table__,
                DynamicPricingRecommendation.__table__,
                DeadStockRecoveryRecommendation.__table__,
            ],
        )
    monkeypatch.setattr(settings, "recommendation_orchestration_enabled", True)
    monkeypatch.setattr(settings, "recommendation_orchestration_shadow_enabled", False)
    monkeypatch.setattr(settings, "recommendation_jobs_enabled", False)
    monkeypatch.setattr(settings, "recommendation_validation_enabled", True)
    monkeypatch.setattr(recommendation_tasks, "SessionLocal", db)
    monkeypatch.setattr(recommendations.celery_app, "send_task", Mock())
    monkeypatch.setattr(
        RecommendationService,
        "generate_ai_recommendation",
        AsyncMock(side_effect=AssertionError("Unexpected LLM call")),
    )
    monkeypatch.setattr(
        RecommendationService, "_emit_recommendation_created", AsyncMock()
    )
    return db


def _seed(db, *, stock=1000, market=True, assessment=True, demand=True):
    product = _product(db)
    now = datetime.now(timezone.utc)
    captured = now - timedelta(minutes=6)
    run_id = None
    with db.begin() as session:
        row = session.get(Product, product.id)
        row.stock_quantity = stock
        row.created_at = now - timedelta(days=90)
        business_date = SalesVelocityService.business_date_for_seller(row.seller, now)
        through = business_date - timedelta(days=1)
        scope = {"seller_id": row.seller_id, "product_id": row.id}
        if market:
            run = _run(session, row, captured, successful_matches=3)
            run_id = run.id
            for value in ("500", "530", "550"):
                _snapshot(
                    session, run, captured, price=Decimal(value), match_score=0.95
                )
        inventory = InventoryHistory(
            **scope,
            snapshot_date=business_date,
            captured_at=captured,
            quantity_on_hand=stock,
            quantity_reserved=0,
            quantity_available=stock,
            source="DAILY_SNAPSHOT",
            content_hash="decision-test",
        )
        session.add(inventory)
        session.flush()
        if demand:
            session.add(
                SalesDataCoverage(
                    **scope,
                    marketplace=MARKETPLACE,
                    source="test",
                    coverage_start_date=through - timedelta(days=29),
                    coverage_end_date=through,
                    completeness_status="COMPLETE",
                    last_imported_at=captured,
                )
            )
            for day in range(10):
                day_start, _ = SalesVelocityService.window_bounds(
                    row.seller, through - timedelta(days=day), 1
                )
                session.add(
                    SalesRecord(
                        **scope,
                        sold_at=day_start + timedelta(hours=12),
                        quantity_sold=10,
                        status="COMPLETED",
                    )
                )
        session.add(
            DemandElasticityEstimate(
                **scope,
                estimation_method="HISTORICAL_ELASTICITY",
                elasticity=Decimal("-0.2"),
                baseline_units=Decimal("100"),
                observation_start=through - timedelta(days=29),
                observation_end=through,
                quality_metrics={},
                confidence=Decimal("90"),
                data_status="SUFFICIENT",
                sample_count=12,
                calculation_version="test",
                calculated_at=captured,
            )
        )
        session.add(
            MarketplaceFeePolicy(
                **scope,
                marketplace=MARKETPLACE,
                version="product-fee",
                percentage_commission_rate=Decimal("0.10"),
                effective_from=captured - timedelta(days=1),
            )
        )
        if assessment:
            session.add(
                DeadStockAssessment(
                    **scope,
                    inventory_snapshot_id=inventory.id,
                    as_of_date=business_date,
                    classification="SLOW_MOVING",
                    eligible_quantity=2,
                    risk_score=Decimal(60),
                    risk_level="MEDIUM",
                    no_sales_state="RECENT_SALE",
                    inventory_age_state="AGE_THRESHOLD_EXCEEDED",
                    inventory_age_days=40,
                    visibility_status="LOW_VISIBILITY",
                    data_status="SUFFICIENT",
                    rule_results={},
                    triggered_rules=["LOW_VISIBILITY"],
                    confidence_score=Decimal(80),
                    calculation_version="test",
                    assessed_at=captured,
                )
            )
            session.add(
                ProductVisibilityMetric(
                    **scope,
                    marketplace=MARKETPLACE,
                    metric_date=business_date,
                    impressions=10,
                    listing_quality_score=Decimal("15.00"),
                    source="test",
                )
            )
    return product, run_id


def _client(db, seller_id):
    app = FastAPI()
    app.include_router(recommendations.router, prefix="/api/v1")

    def session_dependency():
        with db() as session:
            yield session

    app.dependency_overrides[get_db] = session_dependency
    app.dependency_overrides[get_current_seller] = lambda: SimpleNamespace(id=seller_id)
    app.dependency_overrides[get_dashboard_event_emitter] = lambda: Mock()
    return TestClient(app)


def _evaluations(decision):
    return {item["engine"]: item for item in decision["evaluations"]}


def test_inventory_snapshot_validates_reserved_and_available():
    with pytest.raises(ValidationError, match="account for reservations"):
        DecisionInventory(
            snapshot_id=uuid4(),
            captured_at=datetime.now(timezone.utc),
            on_hand_units=5,
            reserved_units=3,
            available_units=5,
        )


def test_api_worker_persists_independent_engines_and_compatible_support(decision_db, monkeypatch):
    monkeypatch.setattr(settings, "recommendation_dashboard_evidence_enabled", True)
    product, run_id = _seed(decision_db, stock=30)
    with _client(decision_db, product.seller_id) as client:
        response = client.post(f"/api/v1/recommendations/generate/{product.id}")
        assert response.status_code == 202, response.text
        job = response.json()["job_id"]
        recommendation_tasks.run_recommendation_job.run(job)
        # Redelivery of the durable job cannot persist another result or outbox row.
        recommendation_tasks.run_recommendation_job.run(job)
        result = client.get(f"/api/v1/recommendations/jobs/{job}").json()
        assert result["status"] == "COMPLETED"
        assert result["result"]["recommendation"]["action"] == "REORDER"
        assert "decision_orchestration" not in result["result"]
        evidence = result["result"]["dashboard_evidence"]
        assert evidence["reorder"]["quantity"] > 0
        assert evidence["available_units"] == 30
        assert {"action": "SEO_FIX", "source": "dead_stock_recovery"} in evidence[
            "supporting_actions"
        ]
        assert evidence["forecasts"] == []
        latest = client.get(f"/api/v1/recommendations/latest/{product.id}").json()
        assert latest["dashboard_evidence"] == evidence
        monkeypatch.setattr(settings, "recommendation_dashboard_evidence_enabled", False)
        rolled_back = client.get(f"/api/v1/recommendations/jobs/{job}").json()
        assert "dashboard_evidence" not in rolled_back["result"]

    with _client(decision_db, uuid4()) as outsider:
        assert outsider.get(f"/api/v1/recommendations/jobs/{job}").status_code == 404
        assert outsider.get(f"/api/v1/recommendations/latest/{product.id}").status_code == 404


    with decision_db() as session:
        saved = session.scalars(select(Recommendation)).one()
        assert saved.suggested_price_min is None
        snapshot = saved.recommendation_context
        orchestration = snapshot["decision_orchestration"]
        evaluations = _evaluations(orchestration)
        assert orchestration["primary_action"] == "REORDER"
        assert orchestration["supporting_advice"][0]["scope"] == "base_price"
        assert orchestration["supporting_advice"][0]["action"] == "HOLD"
        assert evaluations["reorder"]["status"] == "selected"
        assert evaluations["dynamic_pricing"]["candidate"]["action_type"] == "RAISE"
        assert evaluations["dynamic_pricing"]["candidate"]["rejection_reasons"] == [
            "INCOMPATIBLE_WITH_PRIMARY_ACTION"
        ]
        assert (
            evaluations["dead_stock_recovery"]["candidate"]["proposed_parameters"][
                "action"
            ]
            == "SEO_FIX"
        )
        assert (
            evaluations["dead_stock_recovery"]["candidate"]["candidate_id"]
            in orchestration["supporting_candidate_ids"]
        )
        assert snapshot["competitor_evidence"]["scrape_run_id"] == str(run_id)
        assert orchestration["inputs"]["effective_fees"]["version"] == "product-fee"
        outbox = session.scalars(select(RagIndexOutbox)).one()
        assert outbox.seller_id == product.seller_id
        assert session.get(Product, product.id).stock_quantity == 30
        assert session.get(Product, product.id).selling_price == Decimal("500")
        for model in (
            ReorderRecommendation,
            DynamicPricingRecommendation,
            DeadStockRecoveryRecommendation,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize(("demand", "expected"), [(True, "REORDER"), (False, "HOLD")])
def test_no_market_does_not_block_independent_inventory_work(
    decision_db, demand, expected
):
    product, _ = _seed(
        decision_db, stock=10, market=False, assessment=False, demand=demand
    )
    with _client(decision_db, product.seller_id) as client:
        response = client.post(f"/api/v1/recommendations/generate/{product.id}")
        assert response.status_code == 202, response.text
        job = response.json()["job_id"]
        recommendation_tasks.run_recommendation_job.run(job)
        assert (
            client.get(f"/api/v1/recommendations/jobs/{job}").json()["result"][
                "recommendation"
            ]["action"]
            == expected
        )
    with decision_db() as session:
        decision = (
            session.scalars(select(Recommendation))
            .one()
            .recommendation_context["decision_orchestration"]
        )
        assert (
            "INSUFFICIENT_FRESH_COMPETITOR_PRICES"
            in _evaluations(decision)["dynamic_pricing"]["reason_codes"]
        )
        assert ("NO_SUPPORTED_ACTION" in decision["reason_codes"]) is (not demand)


@pytest.mark.parametrize("risk_evaluation", [False, True])
def test_final_exact_guard_rejects_changed_fee_and_reselects_recovery(
    decision_db, monkeypatch, risk_evaluation
):
    monkeypatch.setattr(
        settings, "recommendation_action_evaluation_enabled", risk_evaluation
    )
    product, run_id = _seed(decision_db)
    with decision_db() as session:
        service = RecommendationService(session)
        owned = service.load_product(product.seller_id, product.id)
        decision = DecisionOrchestrator(session).evaluate(
            owned, _collect(session, owned, scrape_run_id=run_id)
        )
        assert decision.action == RecommendationAction.RAISE
        assert decision.target_price is not None
        with decision_db.begin() as other:
            other.execute(
                update(MarketplaceFeePolicy)
                .where(MarketplaceFeePolicy.product_id == product.id)
                .values(
                    percentage_commission_rate=Decimal("0.85"),
                )
            )
        locked = service.load_product(
            product.seller_id, product.id, for_persistence=True
        )
        saved = service.save_recommendation(
            locked, None, {}, decision.analytics, decision=decision
        )

    assert saved.action == RecommendationAction.HOLD
    assert saved.suggested_price_min is None
    orchestration = saved.recommendation_context["decision_orchestration"]
    evaluations = _evaluations(orchestration)
    pricing = evaluations["dynamic_pricing"]
    assert pricing["status"] == "rejected"
    assert "MARGIN_GUARD_BLOCKED" in pricing["candidate"]["rejection_reasons"]
    assert (
        Decimal(pricing["final_margin_guard"]["candidate_price"])
        == decision.target_price
    )
    assert (
        orchestration["primary_candidate_id"]
        == evaluations["dead_stock_recovery"]["candidate"]["candidate_id"]
    )

    if risk_evaluation:
        audit = pricing["action_evaluation"]
        assert audit["financial_safety"] == "blocked"
        assert audit["score"] is None
        assert "MARGIN_GUARD_BLOCKED" in audit["hard_rejections"]


def test_scope_is_required_across_api_context_and_worker(decision_db):
    product, _ = _seed(decision_db, market=False)
    outsider = _product(decision_db)
    with _client(decision_db, outsider.seller_id) as client:
        assert (
            client.post(f"/api/v1/recommendations/generate/{product.id}").status_code
            == 404
        )
    with decision_db() as session:
        service = RecommendationService(session)
        own = service.load_product(product.seller_id, product.id)
        other_evidence = _collect(session, outsider)
        with pytest.raises(ValueError, match="different seller or product"):
            DecisionOrchestrator(session).evaluate(own, other_evidence)
        decision = DecisionOrchestrator(session).evaluate(own, _collect(session, own))
        with pytest.raises(ValueError, match="another seller or product"):
            DecisionOrchestrator(session).finalize(outsider, decision)
        data = decision.context.model_dump()
        data["competitors"] = other_evidence
        with pytest.raises(ValidationError, match="Competitor evidence"):
            RecommendationDecisionContext.model_validate(data)


def test_shadow_compares_but_keeps_legacy_response(decision_db, monkeypatch, caplog):
    product, _ = _seed(decision_db, stock=30, market=False, assessment=False)
    monkeypatch.setattr(settings, "recommendation_orchestration_enabled", False)
    monkeypatch.setattr(settings, "recommendation_jobs_enabled", True)
    monkeypatch.setattr(settings, "recommendation_orchestration_shadow_enabled", True)
    monkeypatch.setattr(settings, "recommendation_validation_enabled", False)
    monkeypatch.setattr(
        RecommendationService,
        "prepare_recommendation",
        lambda *args, **kwargs: (
            {},
            {
                "business_signals_version": 1,
                "action": "HOLD",
                "confidence": 0.0,
                "reason_codes": [],
                "inventory_evidence": {"demand_status": "INSUFFICIENT"},
            },
            None,
        ),
    )
    caplog.set_level("INFO")
    with _client(decision_db, product.seller_id) as client:
        response = client.post(f"/api/v1/recommendations/generate/{product.id}")
        job = response.json()["job_id"]
        recommendation_tasks.run_recommendation_job.run(job)
        assert (
            client.get(f"/api/v1/recommendations/jobs/{job}").json()["result"][
                "recommendation"
            ]["action"]
            == "HOLD"
        )
    with decision_db() as session:
        saved = session.scalars(select(Recommendation)).one()
        assert "decision_orchestration" not in saved.recommendation_context
        assert session.scalar(select(func.count()).select_from(RagIndexOutbox)) == 1
    assert "legacy_action=HOLD orchestrated_action=REORDER match=False" in caplog.text


def test_final_freshness_rejects_price_using_expired_market_evidence(decision_db):
    product, run_id = _seed(decision_db, assessment=False)
    with decision_db() as session:
        owned = RecommendationService(session).load_product(
            product.seller_id, product.id
        )
        orchestrator = DecisionOrchestrator(session)
        decision = orchestrator.evaluate(
            owned, _collect(session, owned, scrape_run_id=run_id)
        )
        assert decision.action == RecommendationAction.RAISE

        final = orchestrator.finalize(
            owned,
            decision,
            at=decision.context.evaluated_at
            + decision.context.competitors.price_max_age,
        )
        assert final.action == RecommendationAction.HOLD
        assert "COMPETITOR_EVIDENCE_STALE" in final.reason_codes
        assert final.analytics["competitor_median_price"] is None
        assert final.analytics["pricing_pressure_score"] is None


def test_final_inventory_refresh_detects_updated_reservations(decision_db):
    product, _ = _seed(decision_db, stock=30, market=False, assessment=False)
    with decision_db() as session:
        service = RecommendationService(session)
        owned = service.load_product(product.seller_id, product.id)
        orchestrator = DecisionOrchestrator(session)
        decision = orchestrator.evaluate(owned, _collect(session, owned))
        assert decision.action == RecommendationAction.REORDER
        assert decision.context.inventory is not None
        with decision_db.begin() as other:
            other.execute(
                update(InventoryHistory)
                .where(InventoryHistory.id == decision.context.inventory.snapshot_id)
                .values(quantity_reserved=15, quantity_available=15)
            )
        locked = service.load_product(
            product.seller_id, product.id, for_persistence=True
        )
        final = orchestrator.finalize(locked, decision)
        assert final.action == RecommendationAction.HOLD
        assert "INVENTORY_EVIDENCE_CHANGED" in final.reason_codes
        assert final.analytics["estimated_days_of_stock_left"] is None


def test_selector_keeps_only_one_directional_price_action(decision_db):
    product, run_id = _seed(decision_db, assessment=False)
    with decision_db() as session:
        owned = RecommendationService(session).load_product(
            product.seller_id, product.id
        )
        decision = DecisionOrchestrator(session).evaluate(
            owned, _collect(session, owned, scrape_run_id=run_id)
        )
    assert decision.primary is not None
    assert decision.action == RecommendationAction.RAISE
    raised = decision.primary.model_dump()
    raised["evaluation_status"] = CandidateStatus.ELIGIBLE
    raise_candidate = RecommendationCandidate.model_validate(raised)
    lowered = raise_candidate.model_dump()
    lowered.update(candidate_id=uuid4(), action_type=RecommendationAction.LOWER)
    lowered["proposed_parameters"]["target_price"] = Decimal("450")
    lowered["estimated_financial_impact"]["profit_delta"] = Decimal("0.01")
    lower_candidate = RecommendationCandidate.model_validate(lowered)

    evaluations = tuple(
        EngineEvaluation(candidate.source_engine, candidate)
        for candidate in (lower_candidate, raise_candidate)
    )
    for ordering in (evaluations, evaluations[::-1]):
        final = select_decision(decision.context, ordering, decision.analytics)
        assert final.action == RecommendationAction.RAISE
        assert not final.supporting
        rejected = next(
            item.candidate
            for item in final.evaluations
            if item.candidate.action_type == RecommendationAction.LOWER
        )
        assert rejected.evaluation_status == CandidateStatus.REJECTED
        assert rejected.rejection_reasons == ("INCOMPATIBLE_WITH_PRIMARY_ACTION",)
