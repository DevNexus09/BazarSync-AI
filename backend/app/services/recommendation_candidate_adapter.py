"""Normalize seller-scoped specialized outputs without generating or saving records."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, StrictBool, ValidationError

from app.models.dead_stock_recovery_recommendation import (
    DeadStockRecoveryAction,
    DeadStockRecoveryRecommendation,
)
from app.models.dynamic_pricing_recommendation import (
    DynamicPricingAction,
    DynamicPricingRecommendation,
)
from app.models.recommendation import RecommendationAction
from app.models.reorder_recommendation import (
    ReorderRecommendation,
    ReorderRecommendationAction,
)
from app.schemas.recommendation_candidate import (
    CandidateEngine,
    CandidateEvidence,
    CandidateStatus,
    EvidenceSource,
    FinancialImpact,
    ForecastRisk,
    Price,
    PricingParameters,
    RecommendationCandidate,
    RecoveryParameters,
    ReorderParameters,
)

SpecializedRecommendation = (
    DynamicPricingRecommendation
    | ReorderRecommendation
    | DeadStockRecoveryRecommendation
)


def to_recommendation_candidate(
    recommendation: SpecializedRecommendation,
    *,
    seller_id: UUID,
    product_id: UUID,
) -> RecommendationCandidate:
    """Project an existing engine result using the caller's verified scope."""
    if recommendation.seller_id != seller_id or recommendation.product_id != product_id:
        raise ValueError(
            "Recommendation is outside the requested seller and product scope."
        )

    if isinstance(recommendation, DynamicPricingRecommendation):
        return _from_pricing(recommendation)
    if isinstance(recommendation, ReorderRecommendation):
        return _from_reorder(recommendation)
    if isinstance(recommendation, DeadStockRecoveryRecommendation):
        return _from_recovery(recommendation)
    raise TypeError("Unsupported specialized recommendation.")


def _from_pricing(row: DynamicPricingRecommendation) -> RecommendationCandidate:
    action = {
        DynamicPricingAction.PRICE_LOWER: RecommendationAction.LOWER,
        DynamicPricingAction.PRICE_RAISE: RecommendationAction.RAISE,
        DynamicPricingAction.HOLD: RecommendationAction.HOLD,
    }[DynamicPricingAction(row.action)]
    target = row.recommended_price if action != RecommendationAction.HOLD else None
    status, reasons = _source_status(row.recommendation_status.value)
    if status == CandidateStatus.ELIGIBLE:
        status, reasons = _price_status(
            row.recommended_price, row.evidence.get("selected")
        )
        if status == CandidateStatus.ELIGIBLE and row.expected_units is None:
            status = CandidateStatus.INSUFFICIENT_EVIDENCE

    impact = None
    if status == CandidateStatus.ELIGIBLE and target is not None:
        if row.revenue_impact is not None or row.profit_impact is not None:
            impact = FinancialImpact(
                currency="BDT",
                revenue_delta=row.revenue_impact,
                profit_delta=row.profit_impact,
            )

    selected = row.evidence.get("selected")
    risk = (
        selected.get("forecast_risk")
        if isinstance(selected, dict) and target is not None
        else None
    )
    return RecommendationCandidate(
        candidate_id=row.id or uuid4(),
        seller_id=row.seller_id,
        product_id=row.product_id,
        source_engine=CandidateEngine.DYNAMIC_PRICING,
        action_type=action,
        proposed_parameters=PricingParameters(
            current_price=row.current_price, target_price=target, currency="BDT"
        ),
        evidence=CandidateEvidence(
            record_id=row.id,
            inputs=_inputs(
                {
                    EvidenceSource.PRICING_ANALYTICS: row.pricing_analytics_id,
                    EvidenceSource.ELASTICITY_ESTIMATE: row.elasticity_estimate_id,
                }
            ),
            snapshot=row.evidence,
        ),
        estimated_financial_impact=impact,
        forecast_risk=ForecastRisk.model_validate(risk) if risk is not None else None,
        confidence=_confidence(row.confidence_score, status),
        calculation_version=row.formula_version,
        generated_at=row.generated_at,
        expires_at=row.expires_at,
        evaluation_status=status,
        rejection_reasons=reasons,
    )


def _from_reorder(row: ReorderRecommendation) -> RecommendationCandidate:
    status, reasons = _source_status(row.recommendation_status.value)
    return RecommendationCandidate(
        candidate_id=row.id or uuid4(),
        seller_id=row.seller_id,
        product_id=row.product_id,
        source_engine=CandidateEngine.REORDER,
        action_type=RecommendationAction(ReorderRecommendationAction(row.action).value),
        proposed_parameters=ReorderParameters(
            quantity=None
            if status == CandidateStatus.INSUFFICIENT_EVIDENCE
            else row.recommended_quantity,
            deadline=row.reorder_deadline,
        ),
        evidence=CandidateEvidence(
            record_id=row.id,
            inputs=_inputs(
                {
                    EvidenceSource.INVENTORY_SNAPSHOT: row.inventory_snapshot_id,
                    EvidenceSource.SALES_VELOCITY: row.sales_velocity_id,
                    EvidenceSource.STOCKOUT_PREDICTION: row.stockout_prediction_id,
                }
            ),
            snapshot=row.evidence,
        ),
        confidence=_confidence(row.confidence_score, status),
        calculation_version=row.calculation_version,
        generated_at=row.generated_at,
        as_of_date=row.as_of_date,
        evaluation_status=status,
        rejection_reasons=reasons,
    )


def _from_recovery(row: DeadStockRecoveryRecommendation) -> RecommendationCandidate:
    action = DeadStockRecoveryAction(row.primary_action)
    status, reasons = _source_status(row.recommendation_status.value)
    price = row.recommended_price
    if status == CandidateStatus.ELIGIBLE and price is not None:
        status, reasons = _recovery_price_status(
            price, action, row.evidence.get("candidate_actions")
        )

    return RecommendationCandidate(
        candidate_id=row.id or uuid4(),
        seller_id=row.seller_id,
        product_id=row.product_id,
        source_engine=CandidateEngine.DEAD_STOCK_RECOVERY,
        action_type=RecommendationAction.HOLD,
        proposed_parameters=RecoveryParameters(
            action=action,
            secondary_actions=tuple(
                DeadStockRecoveryAction(item) for item in row.secondary_actions
            ),
            promotional_price=price,
            currency="BDT" if price is not None else None,
            discount_rate=row.recommended_discount_rate,
            duration_days=row.suggested_duration_days,
            quantity=row.recommended_quantity,
        ),
        evidence=CandidateEvidence.model_validate(
            {
                "record_id": row.id,
                "inputs": _inputs(
                    {EvidenceSource.DEAD_STOCK_ASSESSMENT: row.dead_stock_assessment_id}
                ),
                "snapshot": {**row.evidence, "rejected_actions": row.rejected_actions},
            }
        ),
        confidence=_confidence(row.confidence_score, status),
        calculation_version=row.calculation_version,
        generated_at=row.generated_at,
        expires_at=row.expires_at,
        evaluation_status=status,
        rejection_reasons=reasons,
    )


def _inputs(
    references: dict[EvidenceSource, UUID | None],
) -> dict[EvidenceSource, UUID]:
    return {
        source: record_id
        for source, record_id in references.items()
        if record_id is not None
    }


def _source_status(status: str) -> tuple[CandidateStatus, tuple[str, ...]]:
    if status == "OPEN":
        return CandidateStatus.ELIGIBLE, ()
    if status == "INSUFFICIENT_DATA":
        return CandidateStatus.INSUFFICIENT_EVIDENCE, ()
    return CandidateStatus.REJECTED, (f"SOURCE_STATUS_{status}",)


def _confidence(score: Decimal, status: CandidateStatus) -> Decimal | None:
    return score if status == CandidateStatus.ELIGIBLE else None


class _PriceCheck(BaseModel):
    candidate_price: Price
    is_allowed: StrictBool
    rejection_reasons: tuple[str, ...]


def _price_status(
    price: Decimal, evidence: object
) -> tuple[CandidateStatus, tuple[str, ...]]:
    try:
        check = _PriceCheck.model_validate(evidence)
    except ValidationError:
        return CandidateStatus.INSUFFICIENT_EVIDENCE, ()
    if check.candidate_price != price:
        return CandidateStatus.REJECTED, ("PRICE_EVIDENCE_MISMATCH",)
    if not check.is_allowed or check.rejection_reasons:
        return CandidateStatus.REJECTED, check.rejection_reasons or (
            "MARGIN_GUARD_REJECTED",
        )
    return CandidateStatus.ELIGIBLE, ()


def _recovery_price_status(
    price: Decimal, action: DeadStockRecoveryAction, candidates: object
) -> tuple[CandidateStatus, tuple[str, ...]]:
    # The service orders its evidence with the primary action first. Alternatives
    # can share an action label and must never authorize the primary price.
    if (
        not isinstance(candidates, list)
        or not candidates
        or not isinstance(candidates[0], dict)
    ):
        return CandidateStatus.INSUFFICIENT_EVIDENCE, ()
    primary = candidates[0]
    if primary.get("action") != action:
        return CandidateStatus.REJECTED, ("RECOVERY_ACTION_EVIDENCE_MISMATCH",)
    evidence = primary.get("evidence")
    if not isinstance(evidence, dict):
        return CandidateStatus.INSUFFICIENT_EVIDENCE, ()
    return _price_status(price, evidence.get("margin_guard"))
