from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.dead_stock_assessment import DeadStockClassification, DeadStockRiskLevel
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.models.recommendation import RecommendationAction
from app.models.reorder_recommendation import ReorderRecommendationStatus
from app.models.pricing_analytics_snapshot import PricingAnalyticsDataStatus
from app.schemas.recommendation_candidate import (
    CandidateEngine,
    CandidateStatus,
    EvidenceSource,
    PricingParameters,
    RecommendationCandidate,
    RecoveryParameters,
    ReorderParameters,
)
from app.services.dead_stock_recovery_service import DeadStockRecoveryService
from app.services.recommendation_candidate_adapter import to_recommendation_candidate
from app.services.reorder_recommendation_service import ReorderRecommendationService
import test_dead_stock_recovery_service as recovery_fixtures
import test_dynamic_pricing_service as pricing_fixtures
import test_reorder_recommendation_service as reorder_fixtures
from test_margin_guard import _guard as real_margin_guard

AS_OF = date(2026, 7, 1)
GENERATED_AT = datetime(2026, 7, 1, tzinfo=timezone.utc)


def normalize(row):
    return to_recommendation_candidate(
        row, seller_id=row.seller_id, product_id=row.product_id
    )


@pytest.fixture
def pricing_row():
    return pricing_fixtures._build(
        analytics=pricing_fixtures._analytics(
            current="120.00", median="100.00", recent=100
        ),
        estimate=pricing_fixtures._estimate(elasticity="-1.5"),
    )


def build_reorder(rate):
    owner = reorder_fixtures.seller()
    product = reorder_fixtures.product(owner, specs={"pack_size": "10"})
    return ReorderRecommendationService(
        repository=reorder_fixtures.FakeReorderRepository()
    ).build_recommendation(
        seller=owner,
        product=product,
        inventory_snapshot=reorder_fixtures.inventory(owner, product, on_hand=40),
        sales_velocity=None
        if rate is None
        else reorder_fixtures.velocity(owner, product, rate=rate),
        stockout_prediction=reorder_fixtures.stockout(owner, product),
        as_of_date=AS_OF,
        generated_at=GENERATED_AT,
        calculation_version="v1",
    )


def build_recovery(action):
    owner = recovery_fixtures.seller()
    product = recovery_fixtures.product(owner, cost=Decimal("20.00"))
    repository = recovery_fixtures.FakeRepo()
    repository.products[product.id] = product
    is_bundle = action == DeadStockRecoveryAction.BUNDLE
    repository.assessments[product.id] = recovery_fixtures.assessment(
        owner,
        product,
        classification=DeadStockClassification.SLOW_MOVING
        if is_bundle
        else DeadStockClassification.AT_RISK,
        risk=DeadStockRiskLevel.MEDIUM if is_bundle else DeadStockRiskLevel.HIGH,
        eligible=20 if is_bundle else 5,
        age=45,
    )
    service = DeadStockRecoveryService(
        repository=repository, margin_guard_factory=lambda _: real_margin_guard()
    )
    row, created = service.generate_for_product(
        seller_id=owner.id, product_id=product.id, generated_at=GENERATED_AT
    )
    assert created
    return row


def test_pricing_candidate_preserves_source_economics(pricing_row):
    candidate = normalize(pricing_row)
    params = candidate.proposed_parameters
    impact = candidate.estimated_financial_impact

    assert candidate.source_engine == CandidateEngine.DYNAMIC_PRICING
    assert candidate.action_type == RecommendationAction.LOWER
    assert candidate.evaluation_status == CandidateStatus.ELIGIBLE
    assert isinstance(params, PricingParameters)
    assert params.target_price == pricing_row.recommended_price
    assert impact is not None
    assert impact.currency == params.currency == "BDT"
    assert impact.revenue_delta == pricing_row.revenue_impact
    assert impact.profit_delta == pricing_row.profit_impact
    assert candidate.evidence.inputs == {
        EvidenceSource.PRICING_ANALYTICS: pricing_row.pricing_analytics_id
    }
    assert candidate.evidence.record_id is None
    assert candidate.evidence.snapshot == pricing_row.evidence
    assert (
        RecommendationCandidate.model_validate_json(candidate.model_dump_json())
        == candidate
    )


def test_reorder_candidate_preserves_units_and_deadline():
    row = build_reorder("10")
    candidate = normalize(row)

    assert candidate.source_engine == CandidateEngine.REORDER
    assert candidate.action_type == RecommendationAction.REORDER
    assert candidate.evaluation_status == CandidateStatus.ELIGIBLE
    assert candidate.proposed_parameters == ReorderParameters(
        quantity=row.recommended_quantity, deadline=row.reorder_deadline
    )
    assert candidate.evidence.inputs == {
        EvidenceSource.INVENTORY_SNAPSHOT: row.inventory_snapshot_id,
        EvidenceSource.SALES_VELOCITY: row.sales_velocity_id,
        EvidenceSource.STOCKOUT_PREDICTION: row.stockout_prediction_id,
    }
    assert candidate.as_of_date == AS_OF
    assert candidate.estimated_financial_impact is None
    assert (
        RecommendationCandidate.model_validate_json(candidate.model_dump_json())
        == candidate
    )


@pytest.mark.parametrize(
    "action", [DeadStockRecoveryAction.DISCOUNT, DeadStockRecoveryAction.BUNDLE]
)
def test_recovery_candidate_preserves_specialized_action_and_evidence(action):
    row = build_recovery(action)
    candidate = normalize(row)

    assert candidate.source_engine == CandidateEngine.DEAD_STOCK_RECOVERY
    assert candidate.action_type == RecommendationAction.HOLD
    assert candidate.evaluation_status == CandidateStatus.ELIGIBLE
    assert isinstance(candidate.proposed_parameters, RecoveryParameters)
    assert candidate.proposed_parameters.action == row.primary_action == action
    assert candidate.proposed_parameters.promotional_price == row.recommended_price
    assert candidate.proposed_parameters.quantity == row.recommended_quantity
    assert candidate.proposed_parameters.secondary_actions == tuple(
        row.secondary_actions
    )
    assert candidate.evidence.inputs == {
        EvidenceSource.DEAD_STOCK_ASSESSMENT: row.dead_stock_assessment_id
    }
    assert candidate.evidence.snapshot["rejected_actions"] == row.rejected_actions
    assert candidate.estimated_financial_impact is None
    assert candidate.candidate_id == candidate.evidence.record_id == row.id
    assert normalize(row) == candidate
    assert (
        RecommendationCandidate.model_validate_json(candidate.model_dump_json())
        == candidate
    )


def test_pricing_optional_metrics_distinguish_missing_and_zero(pricing_row):
    pricing_row.profit_impact = None
    pricing_row.revenue_impact = Decimal("0")
    impact = normalize(pricing_row).estimated_financial_impact
    assert impact is not None
    assert impact.profit_delta is None
    assert impact.revenue_delta == Decimal("0")

    pricing_row.revenue_impact = None
    candidate = normalize(pricing_row)
    assert candidate.estimated_financial_impact is None
    assert candidate.evaluation_status == CandidateStatus.ELIGIBLE


def test_reorder_missing_evidence_differs_from_zero_sales():
    missing_row = build_reorder(None)
    missing = normalize(missing_row)
    zero = normalize(build_reorder("0"))

    assert missing.evaluation_status == CandidateStatus.INSUFFICIENT_EVIDENCE
    assert missing.proposed_parameters == ReorderParameters(quantity=None)
    assert missing_row.recommended_quantity == 0
    assert missing.confidence is None
    assert missing.evidence.snapshot["insufficient_reason"] == "missing_sales_velocity"
    assert zero.evaluation_status == CandidateStatus.ELIGIBLE
    assert zero.proposed_parameters == ReorderParameters(quantity=0)


def test_stale_pricing_keeps_source_evidence_and_omits_the_target():
    row = pricing_fixtures._build(
        analytics=pricing_fixtures._analytics(status=PricingAnalyticsDataStatus.STALE)
    )
    candidate = normalize(row)

    assert candidate.evaluation_status == CandidateStatus.INSUFFICIENT_EVIDENCE
    assert candidate.action_type == RecommendationAction.HOLD
    assert isinstance(candidate.proposed_parameters, PricingParameters)
    assert candidate.proposed_parameters.target_price is None
    assert candidate.estimated_financial_impact is None
    assert (
        Decimal(candidate.evidence.snapshot["selected"]["candidate_price"])
        == row.recommended_price
    )


def test_pricing_guard_rejection_of_engine_fallback():
    row = pricing_fixtures._build(
        guard_factory=lambda price: pricing_fixtures._guard(price, allowed=False)
    )
    candidate = normalize(row)

    assert candidate.evaluation_status == CandidateStatus.REJECTED
    assert candidate.rejection_reasons == ("BELOW_MINIMUM_SAFE_PRICE",)
    assert candidate.estimated_financial_impact is None
    assert (
        RecommendationCandidate.model_validate_json(candidate.model_dump_json())
        == candidate
    )


@pytest.mark.parametrize("guard_price", [None, "1.00"])
def test_pricing_requires_guard_evidence_for_exact_price(pricing_row, guard_price):
    if guard_price is None:
        del pricing_row.evidence["selected"]
    else:
        pricing_row.evidence["selected"]["candidate_price"] = guard_price
    candidate = normalize(pricing_row)

    if guard_price is None:
        assert candidate.evaluation_status == CandidateStatus.INSUFFICIENT_EVIDENCE
    else:
        assert candidate.evaluation_status == CandidateStatus.REJECTED
        assert candidate.rejection_reasons == ("PRICE_EVIDENCE_MISMATCH",)
    assert candidate.estimated_financial_impact is None


def test_recovery_guard_from_another_candidate_cannot_authorize_primary_price():
    row = build_recovery(DeadStockRecoveryAction.DISCOUNT)
    candidates = row.evidence["candidate_actions"]
    other = deepcopy(candidates[0])
    candidates[0]["evidence"]["margin_guard"]["candidate_price"] = "1.00"
    candidates.append(other)

    candidate = normalize(row)
    assert candidate.evaluation_status == CandidateStatus.REJECTED
    assert candidate.rejection_reasons == ("PRICE_EVIDENCE_MISMATCH",)


def test_inactive_source_record_is_rejected():
    row = build_reorder("10")
    row.recommendation_status = ReorderRecommendationStatus.DISMISSED
    candidate = normalize(row)
    assert candidate.evaluation_status == CandidateStatus.REJECTED
    assert candidate.rejection_reasons == ("SOURCE_STATUS_DISMISSED",)


@pytest.mark.parametrize("field", ["seller_id", "product_id"])
def test_normalization_requires_matching_scope(pricing_row, field):
    scope = {"seller_id": pricing_row.seller_id, "product_id": pricing_row.product_id}
    scope[field] = uuid4()
    with pytest.raises(
        ValueError, match="outside the requested seller and product scope"
    ):
        to_recommendation_candidate(pricing_row, **scope)


@pytest.mark.parametrize("price", ["0", "-1", "NaN", "Infinity", "12.001", "140.00"])
def test_rejects_invalid_lower_target(pricing_row, price):
    data = normalize(pricing_row).model_dump()
    data["proposed_parameters"]["target_price"] = price
    with pytest.raises(ValidationError):
        RecommendationCandidate.model_validate(data)


@pytest.mark.parametrize("quantity", [None, 0, -1, 1.5, "5", True])
def test_rejects_invalid_reorder_quantity(quantity):
    data = normalize(build_reorder("10")).model_dump()
    data["proposed_parameters"]["quantity"] = quantity
    with pytest.raises(ValidationError):
        RecommendationCandidate.model_validate(data)


@pytest.mark.parametrize(
    "field,currency",
    [
        ("estimated_financial_impact", "USD"),
        ("proposed_parameters", "bdt"),
        ("proposed_parameters", "BD"),
    ],
)
def test_rejects_inconsistent_or_invalid_currency(pricing_row, field, currency):
    data = normalize(pricing_row).model_dump()
    data[field]["currency"] = currency
    with pytest.raises(ValidationError):
        RecommendationCandidate.model_validate(data)


@pytest.mark.parametrize("action", ["FLASH_SALE", "REORDER", "HOLD"])
def test_invalid_action_for_pricing_parameters(pricing_row, action):
    data = normalize(pricing_row).model_dump()
    data["action_type"] = action
    with pytest.raises(ValidationError):
        RecommendationCandidate.model_validate(data)


def test_invalid_recovery_action_parameters():
    with pytest.raises(ValidationError):
        RecoveryParameters(
            action=DeadStockRecoveryAction.SEO_FIX, promotional_price=Decimal("100")
        )
    with pytest.raises(ValidationError):
        RecoveryParameters(action=DeadStockRecoveryAction.FLASH_SALE)
    with pytest.raises(ValidationError):
        RecoveryParameters(
            action=DeadStockRecoveryAction.DISCOUNT,
            promotional_price=Decimal("100"),
            currency="BDT",
            discount_rate=Decimal("1"),
            quantity=10,
        )


def test_evaluation_status_distinguishes_generated_selected_and_rejected(pricing_row):
    data = normalize(pricing_row).model_dump()
    del data["evaluation_status"]
    assert (
        RecommendationCandidate.model_validate(data).evaluation_status
        == CandidateStatus.GENERATED
    )
    data["evaluation_status"] = CandidateStatus.SELECTED
    assert (
        RecommendationCandidate.model_validate(data).evaluation_status
        == CandidateStatus.SELECTED
    )
    data["evaluation_status"] = CandidateStatus.REJECTED
    with pytest.raises(ValidationError, match="require rejection reasons"):
        RecommendationCandidate.model_validate(data)


def test_evidence_is_required_and_detached_from_specialized_output(pricing_row):
    pricing_row.evidence[" raw key "] = " raw value "
    candidate = normalize(pricing_row)
    assert candidate.evidence.snapshot == pricing_row.evidence
    candidate.evidence.snapshot["selected"]["is_allowed"] = False
    assert pricing_row.evidence["selected"]["is_allowed"] is True

    data = candidate.model_dump()
    data["evidence"]["snapshot"] = {}
    with pytest.raises(ValidationError):
        RecommendationCandidate.model_validate(data)
