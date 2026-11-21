from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.models.recommendation import Recommendation
from app.services.recommendation_service import RecommendationService
from app.services.recommendation_evidence_service import (
    CompetitorEvidence,
    FieldEvidence,
    Freshness,
    RecommendationEvidence,
)
from app.services.recommendation_evidence_validator import (
    InvalidRecommendationEvidence,
    RecommendationEvidenceValidator,
)

AT = datetime(2026, 11, 15, tzinfo=timezone.utc)
D = Decimal


@pytest.fixture
def inputs():
    product = SimpleNamespace(
        id=uuid4(),
        seller_id=uuid4(),
        selling_price=D(100),
        supplier_lead_time=7,
        stock_quantity=0,
    )
    fresh = FieldEvidence(Freshness.FRESH, AT - timedelta(minutes=1))
    rows = tuple(
        CompetitorEvidence(uuid4(), uuid4(), D(80), "IN_STOCK", fresh, fresh, 0.95)
        for _ in range(3)
    )
    evidence = RecommendationEvidence(
        product.seller_id,
        product.id,
        uuid4(),
        AT,
        timedelta(hours=24),
        timedelta(hours=6),
        rows,
    )
    result = Mock(
        is_allowed=True,
        candidate_price=D(80),
        minimum_safe_price=D(70),
        unit_profit=D(15),
        margin_rate=D("0.1875"),
        policy_version="test",
    )
    result.to_evidence.return_value = {}
    guard = Mock()
    guard.validate_candidate.return_value = result
    analytics = {
        "action": "LOWER",
        "confidence": 0.99,
        "reason_codes": [],
        "candidate_price": "80",
        "competitor_median_price": "80",
        "pricing_evidence": {},
        "inventory_evidence": {
            "demand_status": "OBSERVED",
            "daily_net_sales_rate": "3",
            "inventory_snapshot_id": str(uuid4()),
            "available_units": 0,
            "on_hand_units": 0,
            "inventory_captured_at": AT.isoformat(),
            "supplier_lead_time_days": 7,
            "reorder": {"dedicated_action": "REORDER", "recommended_quantity": 100},
        },
    }
    return SimpleNamespace(
        product=product,
        evidence=evidence,
        guard=guard,
        result=result,
        analytics=analytics,
    )


def assess(inputs):
    return RecommendationEvidenceValidator(inputs.guard).assess(
        inputs.product,
        inputs.evidence,
        inputs.analytics,
        now=AT,
    )


def test_stale_prices_never_approve_strong_signal(inputs):
    inputs.evidence = replace(
        inputs.evidence,
        observations=tuple(
            replace(
                row,
                price_evidence=FieldEvidence(Freshness.FRESH, AT - timedelta(days=2)),
            )
            for row in inputs.evidence.observations
        ),
    )
    assessment = assess(inputs)
    assert (assessment.action, assessment.confidence) == ("HOLD", "LOW")
    assert "STALE_COMPETITOR_DATA" in assessment.reason_codes
    assert assessment.market_metrics["competitor_median_price"] is None
    inputs.guard.validate_candidate.assert_not_called()


@pytest.mark.parametrize("score", [None, 0.4, float("nan")])
def test_many_poor_or_unverified_matches_cannot_substitute_for_quality(inputs, score):
    inputs.evidence = replace(
        inputs.evidence,
        observations=tuple(
            replace(
                inputs.evidence.observations[0],
                match_score=score,
                snapshot_id=uuid4(),
                competitor_id=uuid4(),
            )
            for _ in range(20)
        ),
    )
    assessment = assess(inputs)
    assert assessment.confidence == "LOW"
    assert assessment.action == "HOLD"
    assert assessment.metrics["data_completeness"]["eligible_price_count"] == 0


def test_two_fresh_comparables_cap_confidence_at_medium(inputs):
    inputs.evidence = replace(
        inputs.evidence, observations=inputs.evidence.observations[:2]
    )
    assessment = assess(inputs)
    assert (assessment.action, assessment.confidence) == ("LOWER", "MEDIUM")


def test_one_listing_cannot_qualify_as_multiple_comparables(inputs):
    listing = inputs.evidence.observations[0]
    inputs.evidence = replace(inputs.evidence, observations=(listing, listing, listing))
    assessment = assess(inputs)
    assert assessment.metrics["data_completeness"]["eligible_price_count"] == 1
    assert (assessment.action, assessment.confidence) == ("HOLD", "LOW")


@pytest.mark.parametrize(
    ("signal", "expected"),
    [(0.499, "LOW"), (0.50, "MEDIUM"), (0.749, "MEDIUM"), (0.75, "HIGH")],
)
def test_confidence_thresholds_with_complete_evidence(inputs, signal, expected):
    inputs.analytics["confidence"] = signal
    assessment = assess(inputs)
    assert assessment.confidence == expected
    assert assessment.metrics["predictive_uncertainty"] is None


def test_unknown_stock_cannot_support_raise(inputs):
    inputs.evidence = replace(
        inputs.evidence,
        observations=tuple(
            replace(row, stock_status="UNKNOWN") for row in inputs.evidence.observations
        ),
    )
    assert assess(inputs).confidence == "MEDIUM"
    inputs.analytics.update(action="RAISE", candidate_price="105")
    assessment = assess(inputs)
    assert assessment.action == "HOLD"
    assert "UNKNOWN_MARKET_AVAILABILITY" in assessment.reason_codes
    assert assessment.market_metrics["out_of_stock_competitor_count"] is None


def test_reorder_requires_positive_demand_and_dedicated_plan(inputs):
    inputs.analytics.update(action="REORDER", candidate_price=None)
    assert assess(inputs).action == "REORDER"
    inputs.analytics["inventory_evidence"]["demand_status"] = (
        "ESTIMATED_FROM_RECORDED_SALES"
    )
    assert assess(inputs).confidence == "MEDIUM"
    inputs.analytics["inventory_evidence"]["demand_status"] = "INSUFFICIENT"
    assessment = assess(inputs)
    assert assessment.action == "HOLD"
    assert "INSUFFICIENT_SALES_HISTORY" in assessment.reason_codes


@pytest.mark.parametrize("reason", ["MISSING_FEE_DATA", "BELOW_MINIMUM_SAFE_PRICE"])
def test_guard_failure_preserves_rejection_evidence(inputs, reason):
    inputs.result.is_allowed = False
    inputs.result.to_evidence.return_value = {"rejection_reasons": [reason]}
    assessment = assess(inputs)
    assert assessment.action == "HOLD"
    assert assessment.candidate_price is None
    assert "MARGIN_GUARD_BLOCKED" in assessment.reason_codes
    assert ("MISSING_FEE_POLICY" in assessment.reason_codes) == (
        reason == "MISSING_FEE_DATA"
    )
    assert assessment.guard["rejection_reasons"] == [reason]


def test_hold_and_scope_rejection(inputs):
    inputs.analytics.update(action="HOLD", candidate_price=None)
    assert assess(inputs).action == "HOLD"
    inputs.evidence = replace(inputs.evidence, seller_id=uuid4())
    with pytest.raises(InvalidRecommendationEvidence, match="different seller"):
        assess(inputs)


def test_save_uses_validated_decision_instead_of_explanation(inputs, monkeypatch):
    inputs.analytics.update(business_signals_version=1, evidence_validation_version=1)
    inputs.evidence = replace(inputs.evidence, observations=())
    monkeypatch.setattr(
        "app.services.recommendation_service.MarginGuard",
        lambda _session: inputs.guard,
    )
    db = Mock(spec=["add", "commit"])
    proposed_explanation = SimpleNamespace(
        recommendation=SimpleNamespace(
            action="RAISE",
            confidence="HIGH",
            reasoning_bn="দাম বাড়ান",
            revenue_opportunity=100,
        )
    )
    saved = RecommendationService(db).save_recommendation(
        inputs.product,
        proposed_explanation,
        {},
        inputs.analytics,
        evidence=inputs.evidence,
    )
    assert (saved.action, saved.confidence) == ("HOLD", "LOW")
    assert saved.reasoning_bn != proposed_explanation.recommendation.reasoning_bn
    assert saved.revenue_opportunity == 0
    assert saved.suggested_price_min is None


@pytest.mark.parametrize(
    "amount", [float("nan"), float("inf"), "NaN", "-Infinity", "invalid"]
)
def test_invalid_monetary_fields_are_rejected(inputs, amount):
    inputs.analytics["pricing_evidence"]["estimated_profit"] = amount
    with pytest.raises(InvalidRecommendationEvidence):
        assess(inputs)


@pytest.mark.parametrize("amount", ["NaN", "Infinity"])
def test_recommendation_model_rejects_nonfinite_money(amount):
    with pytest.raises(ValueError, match="finite"):
        Recommendation(revenue_opportunity=D(amount))
    with pytest.raises(ValueError, match="finite"):
        Recommendation(suggested_price_min=D(amount))
