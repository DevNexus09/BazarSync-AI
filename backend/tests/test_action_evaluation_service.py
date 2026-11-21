from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import settings
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.models.recommendation import Recommendation, RecommendationAction
from app.schemas.pricing_policy import (
    MarketplaceFeePolicyResponse,
    PricingPolicyResponse,
)
from app.schemas.recommendation_candidate import (
    CandidateEngine,
    CandidateEvidence,
    CandidateStatus,
    EvidenceSource,
    FinancialImpact,
    ForecastInterval,
    ForecastRisk,
    PricingParameters,
    RecommendationCandidate,
    RecoveryParameters,
    ReorderParameters,
)
from app.schemas.recommendation_decision import (
    DecisionInventory,
    DecisionSales,
    RecommendationDecisionContext,
)
from app.services.action_evaluation_service import (
    ActionEvaluationPolicy,
    ActionEvaluationService,
)
from app.services.recommendation_evidence_service import (
    CompetitorEvidence,
    FieldEvidence,
    Freshness,
    RecommendationEvidence,
)
from app.services.recommendation_selection import EngineEvaluation, select_decision
from app.tasks import recommendation_tasks
from test_decision_orchestrator import _client, _evaluations, _seed

pytest_plugins = ("test_decision_orchestrator",)

D = Decimal
NOW = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)


@pytest.fixture
def context():
    seller, product = uuid4(), uuid4()
    scope = {"seller_id": seller, "product_id": product}
    fresh = FieldEvidence(Freshness.FRESH, NOW - timedelta(minutes=5))
    observations = tuple(
        CompetitorEvidence(uuid4(), uuid4(), D("105"), "IN_STOCK", fresh, fresh, 0.95)
        for _ in range(2)
    )
    return RecommendationDecisionContext(
        **scope,
        evaluated_at=NOW,
        business_date=NOW.date(),
        product_updated_at=NOW,
        current_price=D("100"),
        unit_cost=D("50"),
        on_hand_units=10,
        supplier_lead_time_days=7,
        policy=PricingPolicyResponse(id=uuid4(), **scope),
        effective_fees=MarketplaceFeePolicyResponse(
            id=uuid4(), **scope, version="effective"
        ),
        inventory=DecisionInventory(
            snapshot_id=uuid4(),
            captured_at=NOW,
            on_hand_units=10,
            reserved_units=0,
            available_units=10,
        ),
        sales=DecisionSales(
            through=NOW.date() - timedelta(days=1),
            version="v1",
            status="OBSERVED",
            rate=D("2"),
            coverage_id=uuid4(),
            valid_records=15,
            sample_days=15,
            window_days=30,
        ),
        competitors=RecommendationEvidence(
            seller,
            product,
            uuid4(),
            NOW,
            timedelta(hours=24),
            timedelta(hours=6),
            observations,
        ),
        validated_competitor_price_count=2,
        quality_flags=(),
        elasticity_estimate_id=uuid4(),
        elasticity_observation_end=NOW.date() - timedelta(days=1),
        dead_stock_assessment_id=None,
        dead_stock_assessed_at=None,
    )


def _price_candidate(
    context,
    *,
    target="110",
    floor="65",
    profit="100",
    method="HISTORICAL_ELASTICITY",
    risk=None,
):
    action = (
        RecommendationAction.RAISE
        if D(target) > context.current_price
        else RecommendationAction.LOWER
    )
    return RecommendationCandidate(
        candidate_id=uuid4(),
        seller_id=context.seller_id,
        product_id=context.product_id,
        source_engine=CandidateEngine.DYNAMIC_PRICING,
        action_type=action,
        proposed_parameters=PricingParameters(
            current_price=context.current_price, target_price=D(target), currency="BDT"
        ),
        evidence=CandidateEvidence(
            inputs={EvidenceSource.ELASTICITY_ESTIMATE: context.elasticity_estimate_id},
            snapshot={
                "selected": {
                    "candidate_price": target,
                    "expected_units": "150",
                    "expected_profit": "3200",
                    "forecast_method": method,
                    "margin_guard": {
                        "candidate_price": target,
                        "minimum_safe_price": floor,
                        "unit_profit": "40",
                        "unit_cost": "50",
                        "marketplace_increment_valid": True,
                        "is_allowed": True,
                        "calculation_version": "margin_guard_v1",
                        "policy_version": "effective",
                        "rejection_reasons": [],
                    },
                }
            },
        ),
        estimated_financial_impact=FinancialImpact(
            currency="BDT", profit_delta=D(profit)
        ),
        forecast_risk=risk,
        confidence=D("99"),
        calculation_version="pricing-v1",
        generated_at=NOW,
        expires_at=NOW + timedelta(hours=72),
        evaluation_status=CandidateStatus.ELIGIBLE,
    )


def _reorder_candidate(context, *, quantity=20, pack=5, minimum=5, days=0):
    return RecommendationCandidate(
        candidate_id=uuid4(),
        seller_id=context.seller_id,
        product_id=context.product_id,
        source_engine=CandidateEngine.REORDER,
        action_type=RecommendationAction.REORDER,
        proposed_parameters=ReorderParameters(
            quantity=quantity, deadline=context.business_date + timedelta(days=days)
        ),
        evidence=CandidateEvidence(
            inputs={EvidenceSource.INVENTORY_SNAPSHOT: context.inventory.snapshot_id},
            snapshot={
                "raw_reorder_quantity": 20,
                "target_stock": 30,
                "minimum_order_quantity": minimum,
                "pack_size": pack,
            },
        ),
        confidence=D("95"),
        calculation_version="reorder-v1",
        generated_at=NOW,
        evaluation_status=CandidateStatus.ELIGIBLE,
    )


def _factor(report, name):
    return next(factor for factor in report.scoring_factors if factor.name == name)


def _evaluation(candidate):
    return EngineEvaluation(candidate.source_engine, candidate)


def test_financial_forecast_is_a_normalized_prediction(context):
    candidate = _price_candidate(context, profit="250")
    evaluator = ActionEvaluationService()
    report = evaluator.evaluate(candidate, context)

    assert report.eligible and report.evidence_sufficient
    assert report.financial_safety == "verified"
    assert _factor(report, "available_inventory").provenance == "measured"
    assert _factor(report, "unit_contribution").provenance == "deterministic_estimate"
    profit = _factor(report, "profit_delta")
    assert profit.provenance == "model_prediction"
    assert profit.raw_value == D("250")
    assert profit.normalized == D("0.25")
    assert _factor(report, "engine_signal").normalized is None
    assert _factor(report, "forecast_uncertainty").provenance == "unsupported"


@pytest.mark.parametrize(
    "failure",
    ["unknown_cost", "unknown_demand", "stale_market", "below_floor", "guard_mismatch"],
)
def test_hard_constraints_prevent_scoring(context, failure):
    candidate = _price_candidate(context, target="90")
    expected = {
        "unknown_cost": "UNIT_COST_UNAVAILABLE",
        "unknown_demand": "PROFIT_FORECAST_UNSUPPORTED",
        "stale_market": "FRESH_MARKET_EVIDENCE_UNAVAILABLE",
        "below_floor": "BELOW_MINIMUM_SAFE_PRICE",
        "guard_mismatch": "EXACT_MARGIN_GUARD_UNVERIFIED",
    }[failure]
    final_guard = None
    if failure == "unknown_cost":
        context = context.model_copy(update={"unit_cost": None})
    elif failure == "unknown_demand":
        candidate = _price_candidate(
            context, target="90", method="CONSERVATIVE_HEURISTIC"
        )
    elif failure == "stale_market":
        context = context.model_copy(update={"validated_competitor_price_count": 0})
    elif failure == "below_floor":
        candidate = _price_candidate(context, target="90", floor="95")
    elif failure == "guard_mismatch":
        final_guard = {
            **candidate.evidence.snapshot["selected"]["margin_guard"],
            "candidate_price": "89",
        }

    report = ActionEvaluationService().evaluate(
        candidate, context, final_guard=final_guard
    )
    assert not report.eligible
    assert report.score is None
    assert not any(factor.normalized is not None for factor in report.scoring_factors)
    assert expected in report.hard_rejections
    if failure in {"unknown_cost", "unknown_demand", "below_floor", "guard_mismatch"}:
        assert _factor(report, "profit_delta").raw_value is None
        assert _factor(report, "profit_delta").provenance == "unsupported"


@pytest.mark.parametrize(
    ("quantity", "pack", "minimum", "reason"),
    [
        (21, 5, 5, "REORDER_PACK_SIZE_VIOLATION"),
        (5, 5, 10, "REORDER_MINIMUM_ORDER_VIOLATION"),
        (-1, 5, 5, "INVALID_REORDER_QUANTITY"),
    ],
)
def test_urgent_reorder_cannot_override_quantity_constraints(
    context, quantity, pack, minimum, reason
):
    candidate = _reorder_candidate(
        context, quantity=max(1, quantity), pack=pack, minimum=minimum
    )
    if quantity < 0:
        params = candidate.proposed_parameters.model_copy(update={"quantity": quantity})
        candidate = candidate.model_copy(update={"proposed_parameters": params})
    report = ActionEvaluationService().evaluate(candidate, context)
    assert report.score is None
    assert reason in report.hard_rejections


def test_reorder_scores_stock_gap_without_assigning_profit(context):
    report = ActionEvaluationService().evaluate(_reorder_candidate(context), context)
    assert report.eligible
    assert report.financial_safety == "unavailable"
    assert _factor(report, "stock_gap").raw_value == 20
    assert _factor(report, "stock_gap").provenance == "deterministic_estimate"
    assert _factor(report, "reorder_urgency").normalized == 1
    assert _factor(report, "profit_delta").raw_value is None


def test_missing_evidence_and_policy_threshold_cause_abstention(context):
    evaluator = ActionEvaluationService(ActionEvaluationPolicy(minimum_score=D("1")))
    candidate = _price_candidate(context)
    decision = select_decision(
        context, (_evaluation(candidate),), {}, evaluator=evaluator
    )
    assert decision.action == RecommendationAction.HOLD
    assert "ACTION_SCORE_BELOW_THRESHOLD" in decision.reason_codes
    snapshot = decision.to_context()
    assert snapshot["action_evaluation_policy"]["version"] == "risk-aware-v1"
    assert snapshot["evaluations"][0]["action_evaluation"]["preference_rejections"] == [
        "ACTION_SCORE_BELOW_THRESHOLD"
    ]
    assert snapshot["evaluations"][0]["action_evaluation"]["hard_rejections"] == []


def test_forecast_uncertainty_and_risk_threshold(context):
    source = dict(
        source="validated_test_model", calculation_version="v2", horizon_days=30
    )
    interval = ForecastInterval(
        kind="prediction_interval",
        metric="demand_units",
        lower=D(80),
        central=D(100),
        upper=D(120),
        coverage_probability=D("0.90"),
    )
    low = ForecastRisk(
        **source,
        interval=interval,
        adverse_outcome="negative_incremental_profit",
        adverse_outcome_probability=D("0.25"),
    )
    high = low.model_copy(update={"adverse_outcome_probability": D("0.61")})
    evaluator = ActionEvaluationService()
    low_report = evaluator.evaluate(_price_candidate(context, risk=low), context)
    high_report = evaluator.evaluate(_price_candidate(context, risk=high), context)
    assert _factor(low_report, "forecast_uncertainty").normalized == D("0.75")
    assert high_report.score is None
    assert high_report.hard_rejections == ("ADVERSE_OUTCOME_RISK_ABOVE_LIMIT",)
    with pytest.raises(ValidationError, match="cannot claim coverage probability"):
        ForecastInterval.model_validate(
            {**interval.model_dump(), "kind": "sensitivity_band"}
        )


def test_scored_selection_ties_and_opposing_prices_are_repeatable(context):
    evaluator = ActionEvaluationService()
    choices = (
        _evaluation(_price_candidate(context, target="90")),
        _evaluation(_price_candidate(context, target="110")),
    )
    decisions = [
        select_decision(context, seq, {}, evaluator=evaluator)
        for seq in (choices, choices[::-1])
    ]
    assert all(
        decision.action == RecommendationAction.LOWER and not decision.supporting
        for decision in decisions
    )
    assert all(
        "INCOMPATIBLE_WITH_PRIMARY_ACTION" in decision.reason_codes
        for decision in decisions
    )
    assert decisions[0].primary.candidate_id == decisions[1].primary.candidate_id


def test_supporting_actions_must_be_compatible_with_each_other(context):
    assessment_id = uuid4()
    context = context.model_copy(
        update={
            "dead_stock_assessment_id": assessment_id,
            "dead_stock_assessed_at": NOW,
        }
    )
    recovery = RecommendationCandidate(
        candidate_id=uuid4(),
        seller_id=context.seller_id,
        product_id=context.product_id,
        source_engine=CandidateEngine.DEAD_STOCK_RECOVERY,
        action_type=RecommendationAction.HOLD,
        proposed_parameters=RecoveryParameters(action=DeadStockRecoveryAction.SEO_FIX),
        evidence=CandidateEvidence(
            inputs={EvidenceSource.DEAD_STOCK_ASSESSMENT: assessment_id},
            snapshot={
                "inputs": {"risk_score": "100"},
                "candidate_actions": [
                    {
                        "action": "SEO_FIX",
                        "evidence": {
                            "triggering_visibility_rules": ["LOW_IMPRESSIONS"],
                        },
                    }
                ],
            },
        ),
        calculation_version="recovery-v1",
        generated_at=NOW,
        evaluation_status=CandidateStatus.ELIGIBLE,
    )
    choices = tuple(
        _evaluation(candidate)
        for candidate in (
            _price_candidate(context, target="110"),
            recovery,
            _price_candidate(context, target="90"),
        )
    )

    decision = select_decision(
        context, choices, {}, evaluator=ActionEvaluationService()
    )

    assert decision.primary and decision.primary.candidate_id == recovery.candidate_id
    assert [item.action_type for item in decision.supporting] == [
        RecommendationAction.LOWER
    ]
    assert "INCOMPATIBLE_WITH_SUPPORTING_ACTION" in decision.reason_codes


def test_scoped_evaluator_rejects_foreign_candidate(context):
    candidate = _price_candidate(context).model_copy(update={"seller_id": uuid4()})
    with pytest.raises(ValueError, match="seller and product scope"):
        ActionEvaluationService().evaluate(candidate, context)


@pytest.mark.parametrize("enabled", [False, True])
def test_worker_persists_versioned_audit_only_when_enabled(
    decision_db, monkeypatch, enabled
):
    monkeypatch.setattr(settings, "recommendation_action_evaluation_enabled", enabled)
    product, _ = _seed(decision_db, stock=30)
    with _client(decision_db, product.seller_id) as client:
        queued = client.post(f"/api/v1/recommendations/generate/{product.id}")
        assert queued.status_code == 202
        job_id = queued.json()["job_id"]
        recommendation_tasks.run_recommendation_job.run(job_id)
        recommendation_tasks.run_recommendation_job.run(job_id)
        status = client.get(f"/api/v1/recommendations/jobs/{job_id}").json()
        assert status["status"] == "COMPLETED"
        assert status["attempts"] == 1
        assert status["result"]["recommendation"]["action"] == "REORDER"
        assert "action_evaluation_policy" not in status["result"]

    with decision_db() as session:
        decision = (
            session.scalars(select(Recommendation))
            .one()
            .recommendation_context["decision_orchestration"]
        )
    assert ("action_evaluation_policy" in decision) is enabled
    if enabled:
        evaluations = _evaluations(decision)
        assert evaluations["reorder"]["action_evaluation"]["eligible"]
        assert (
            evaluations["reorder"]["candidate"]["candidate_id"]
            == decision["primary_candidate_id"]
        )
        pricing = evaluations["dynamic_pricing"]
        assert pricing["candidate"]["evaluation_status"] == "rejected"
        assert pricing["action_evaluation"]["financial_safety"] == "verified"
        assert (
            pricing["action_evaluation"]["forecast_risk"]["interval"]["kind"]
            == "sensitivity_band"
        )
        assert (
            pricing["action_evaluation"]["forecast_risk"]["interval"][
                "coverage_probability"
            ]
            is None
        )
        assert (
            pricing["final_margin_guard"]["candidate_price"]
            == pricing["candidate"]["proposed_parameters"]["target_price"]
        )
