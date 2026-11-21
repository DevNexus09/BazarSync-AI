"""Check action constraints and compare supported proposals on normalized factors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from app.analytics.metrics import PricingConfig
from app.core.config import settings
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.models.demand_elasticity_estimate import DemandEstimationMethod
from app.models.recommendation import RecommendationAction
from app.models.reorder_recommendation import FORECAST_REORDER_VERSION
from app.schemas.forecast_inference import ForecastInferenceResult
from app.schemas.recommendation_candidate import (
    MAX_PERSISTED_PRICE,
    CandidateStatus,
    EvidenceSource,
    ForecastRisk,
    PricingParameters,
    RecommendationCandidate,
    RecoveryParameters,
    ReorderParameters,
)
from app.schemas.recommendation_decision import RecommendationDecisionContext
from app.services.forecast_reorder_service import (
    approved_reorder_forecast,
)

ZERO = Decimal(0)
ONE = Decimal(1)
Rate = Annotated[Decimal, Field(ge=0, le=1)]
Provenance = Literal[
    "measured", "deterministic_estimate", "model_prediction", "unsupported"
]
Safety = Literal["verified", "blocked", "unavailable", "not_applicable"]
PRICE_ACTIONS = {RecommendationAction.LOWER, RecommendationAction.RAISE}
STOCK_RECOVERY = {
    DeadStockRecoveryAction.DISCOUNT,
    DeadStockRecoveryAction.FLASH_SALE,
    DeadStockRecoveryAction.BUNDLE,
}


class ActionEvaluationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    version: Literal["risk-aware-v1"] = "risk-aware-v1"
    minimum_score: Rate = Decimal("0.50")
    profit_reference_bdt: Decimal = Field(default=Decimal("1000"), gt=0)
    maximum_adverse_probability: Rate = Decimal("0.60")
    inventory_max_age_hours: int = Field(default=48, gt=0)
    minimum_market_prices: int = Field(
        default=PricingConfig().min_competitor_count, gt=0
    )
    reorder_horizon_days: int = Field(default=14, ge=0)
    reorder_priority_window_days: int = Field(default=0, ge=0)
    evidence_weight: Decimal = Field(default=Decimal("0.35"), gt=0)
    urgency_weight: Decimal = Field(default=Decimal("0.30"), gt=0)
    benefit_weight: Decimal = Field(default=Decimal("0.20"), gt=0)
    feasibility_weight: Decimal = Field(default=Decimal("0.15"), gt=0)
    uncertainty_weight: Decimal = Field(default=Decimal("0.15"), gt=0)

    @classmethod
    def configured(cls) -> ActionEvaluationPolicy:
        return cls(
            minimum_score=settings.recommendation_action_min_score,
            profit_reference_bdt=settings.recommendation_action_profit_reference_bdt,
            maximum_adverse_probability=settings.recommendation_action_max_adverse_risk,
            inventory_max_age_hours=settings.recommendation_inventory_max_age_hours,
            reorder_horizon_days=settings.reorder_maximum_recommendation_horizon_days,
        )


class EvaluationFactor(BaseModel):
    name: str
    provenance: Provenance
    source: str
    raw_value: Decimal | None
    unit: str
    normalized: Rate | None = None
    weight: Decimal = ZERO


class ActionEvaluation(BaseModel):
    evaluated_at: AwareDatetime
    eligible: bool
    evidence_sufficient: bool
    actionable: bool
    priority_tier: Literal["due_reorder", "normal"] | None
    evidence_gaps: tuple[str, ...]
    financial_safety: Safety
    hard_rejections: tuple[str, ...]
    preference_rejections: tuple[str, ...]
    score: Rate | None
    scoring_factors: tuple[EvaluationFactor, ...]
    forecast_risk: ForecastRisk | None


@dataclass(frozen=True)
class _Checks:
    missing_evidence: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    financial_safety: Safety = "not_applicable"
    guard: dict[str, object] | None = None


class ActionEvaluationService:
    def __init__(self, policy: ActionEvaluationPolicy | None = None) -> None:
        self.policy = policy or ActionEvaluationPolicy.configured()

    def evaluate(
        self,
        candidate: RecommendationCandidate,
        context: RecommendationDecisionContext,
        *,
        final_guard: dict[str, object] | None = None,
        at: datetime | None = None,
    ) -> ActionEvaluation:
        if (candidate.seller_id, candidate.product_id) != (
            context.seller_id,
            context.product_id,
        ):
            raise ValueError(
                "Candidate is outside the decision's seller and product scope."
            )

        evaluated_at = at or context.evaluated_at
        if evaluated_at.utcoffset() is None:
            raise ValueError("Action evaluation time must include a timezone.")
        params = candidate.proposed_parameters
        price = candidate_price(candidate)
        actionable = candidate.action_type != RecommendationAction.HOLD or (
            isinstance(params, RecoveryParameters)
            and params.action != DeadStockRecoveryAction.HOLD
        )
        stock = context.inventory
        source = candidate.evidence.snapshot
        recovery = _recovery_evidence(candidate)
        checks = self._financial_checks(candidate, context, price, final_guard)
        missing = list(checks.missing_evidence)
        rejected = [*candidate.rejection_reasons, *checks.rejected]
        if candidate.evaluation_status not in {
            CandidateStatus.ELIGIBLE,
            CandidateStatus.SELECTED,
            CandidateStatus.REJECTED,
        }:
            missing.append("SOURCE_CANDIDATE_NOT_ELIGIBLE")
        if (
            isinstance(params, ReorderParameters)
            and candidate.action_type == RecommendationAction.REORDER
        ):
            self._check_reorder(candidate, context, params, missing, rejected)
        if isinstance(params, RecoveryParameters) and actionable:
            if (
                context.dead_stock_assessment_id is None
                or candidate.evidence.inputs.get(EvidenceSource.DEAD_STOCK_ASSESSMENT)
                != context.dead_stock_assessment_id
            ):
                missing.append("RECOVERY_ASSESSMENT_UNAVAILABLE")
            if params.action in STOCK_RECOVERY and (
                stock is None
                or params.quantity is None
                or not 0 < params.quantity <= stock.available_units
            ):
                rejected.append("RECOVERY_QUANTITY_UNSUPPORTED")
            if params.action == DeadStockRecoveryAction.SEO_FIX and not recovery.get(
                "triggering_visibility_rules"
            ):
                missing.append("LISTING_EVIDENCE_UNAVAILABLE")
        if candidate.action_type in PRICE_ACTIONS and (
            stock is None or stock.available_units <= 0
        ):
            missing.append("NO_VERIFIED_SELLABLE_INVENTORY")
        if candidate.action_type == RecommendationAction.LOWER and _object(
            source.get("selected")
        ).get("inventory_risk_level") in ("HIGH", "CRITICAL"):
            rejected.append("LOWER_CONFLICTS_WITH_NEAR_TERM_STOCKOUT")

        if candidate.action_type in PRICE_ACTIONS and price is None:
            missing.append("PRICE_TARGET_UNAVAILABLE")
        if (
            stock is not None
            and (
                isinstance(params, ReorderParameters)
                or candidate.action_type in PRICE_ACTIONS
                or isinstance(params, RecoveryParameters)
                and params.action in STOCK_RECOVERY
            )
            and not timedelta(0)
            <= evaluated_at - stock.captured_at
            <= timedelta(hours=self.policy.inventory_max_age_hours)
        ):
            missing.append("INVENTORY_EVIDENCE_STALE")
        if (
            isinstance(params, RecoveryParameters)
            and actionable
            and (
                context.dead_stock_assessed_at is None
                or not timedelta(0)
                <= evaluated_at - context.dead_stock_assessed_at
                <= timedelta(hours=self.policy.inventory_max_age_hours)
            )
        ):
            missing.append("RECOVERY_ASSESSMENT_STALE_OR_UNAVAILABLE")
        if candidate.expires_at is not None and (
            candidate.expires_at.utcoffset() is None
            or candidate.expires_at <= evaluated_at
        ):
            rejected.append("CANDIDATE_EXPIRED")
        missing.extend(
            reason
            for reason in candidate.rejection_reasons
            if reason
            in {
                "COMPETITOR_EVIDENCE_STALE",
                "DEAD_STOCK_ASSESSMENT_STALE",
                "INVENTORY_EVIDENCE_CHANGED",
                "PRODUCT_INPUTS_CHANGED",
            }
        )

        risk = candidate.forecast_risk
        if (
            risk
            and risk.adverse_outcome_probability is not None
            and risk.adverse_outcome_probability
            > self.policy.maximum_adverse_probability
        ):
            rejected.append("ADVERSE_OUTCOME_RISK_ABOVE_LIMIT")
        hard = tuple(dict.fromkeys([*missing, *rejected]))
        # Raw provenance remains in the audit even when a constraint blocks scoring.
        factors = self._factors(
            candidate,
            context,
            checks,
            recovery,
            score=actionable and not hard,
            benefit_supported=not missing and checks.financial_safety == "verified",
        )
        scored = [
            factor
            for factor in factors
            if factor.normalized is not None and factor.weight > ZERO
        ]
        score = (
            sum(
                (
                    factor.normalized * factor.weight
                    for factor in scored
                    if factor.normalized is not None
                ),
                ZERO,
            )
            / sum((factor.weight for factor in scored), ZERO)
            if scored
            else None
        )
        preferences = (
            ("ACTION_SCORE_BELOW_THRESHOLD",)
            if actionable
            and not hard
            and (score is None or score < self.policy.minimum_score)
            else ()
        )
        eligible = not hard and not preferences
        due_reorder = (
            isinstance(params, ReorderParameters)
            and candidate.action_type == RecommendationAction.REORDER
            and params.deadline is not None
            and (params.deadline - context.business_date).days
            <= self.policy.reorder_priority_window_days
        )
        return ActionEvaluation(
            evaluated_at=evaluated_at,
            eligible=eligible,
            priority_tier=("due_reorder" if due_reorder else "normal")
            if eligible and actionable
            else None,
            evidence_gaps=tuple(dict.fromkeys(missing)),
            evidence_sufficient=not missing,
            actionable=actionable,
            financial_safety=checks.financial_safety,
            hard_rejections=hard,
            preference_rejections=preferences,
            score=score,
            scoring_factors=factors,
            forecast_risk=risk,
        )

    def _financial_checks(
        self,
        candidate: RecommendationCandidate,
        context: RecommendationDecisionContext,
        price: Decimal | None,
        final_guard: dict[str, object] | None,
    ) -> _Checks:
        if price is None:
            params = candidate.proposed_parameters
            if candidate.action_type == RecommendationAction.REORDER or (
                isinstance(params, RecoveryParameters)
                and params.action == DeadStockRecoveryAction.BUNDLE
            ):
                return _Checks(financial_safety="unavailable")
            return _Checks()
        missing = []
        rejected = []
        proof = _price_proof(candidate) if final_guard is None else final_guard
        if context.unit_cost is None:
            missing.append("UNIT_COST_UNAVAILABLE")
        if (
            context.effective_fees is None
            or context.effective_fees.id is None
            or context.policy is None
        ):
            missing.append("EFFECTIVE_PRICE_TERMS_UNAVAILABLE")
        elif (
            context.effective_fees.currency.upper() != "BDT"
            or context.policy.currency.upper() != "BDT"
        ):
            rejected.append("UNSUPPORTED_CURRENCY")
        if not proof:
            missing.append("EXACT_MARGIN_GUARD_UNAVAILABLE")
        else:
            floor = _number(proof.get("minimum_safe_price"))
            unit_profit = _number(proof.get("unit_profit"))
            if unit_profit is not None and unit_profit < ZERO:
                rejected.append("NEGATIVE_UNIT_PROFIT")
            if floor is not None and price < floor:
                rejected.append("BELOW_MINIMUM_SAFE_PRICE")
            if proof.get("is_allowed") is False:
                rejected.append("MARGIN_GUARD_BLOCKED")
                raw_reasons = proof.get("rejection_reasons")
                if isinstance(raw_reasons, list):
                    rejected.extend(
                        reason for reason in raw_reasons if isinstance(reason, str)
                    )
            elif (
                proof.get("is_allowed") is not True
                or floor is None
                or floor < 0
                or _number(proof.get("candidate_price")) != price
                or context.unit_cost is None
                or _number(proof.get("unit_cost")) != context.unit_cost
                or proof.get("marketplace_increment_valid") is not True
                or not proof.get("calculation_version")
                or unit_profit is None
                or context.effective_fees is None
                or proof.get("policy_version") != context.effective_fees.version
                or proof.get("rejection_reasons") != []
            ):
                missing.append("EXACT_MARGIN_GUARD_UNVERIFIED")

        if price <= ZERO or price > MAX_PERSISTED_PRICE:
            rejected.append("PRICE_OUTSIDE_SUPPORTED_RANGE")
        if isinstance(candidate.proposed_parameters, PricingParameters):
            params = candidate.proposed_parameters
            if (
                context.current_price is None
                or params.current_price != context.current_price
                or (
                    candidate.action_type == RecommendationAction.LOWER
                    and price >= params.current_price
                )
                or (
                    candidate.action_type == RecommendationAction.RAISE
                    and price <= params.current_price
                )
            ):
                rejected.append("CURRENT_PRICE_EVIDENCE_MISMATCH")
            if (
                context.competitors.scrape_run_id is None
                or context.validated_competitor_price_count
                > len(context.competitors.observations)
                or context.validated_competitor_price_count
                < self.policy.minimum_market_prices
            ):
                missing.append("FRESH_MARKET_EVIDENCE_UNAVAILABLE")
            profit = candidate.estimated_financial_impact
            if (
                not _supported_price_response(candidate, context)
                or profit is None
                or profit.profit_delta is None
            ):
                missing.append("PROFIT_FORECAST_UNSUPPORTED")
            elif profit.profit_delta <= ZERO:
                rejected.append("POSITIVE_PROFIT_IMPACT_UNSUPPORTED")
        elif context.current_price is None or price >= context.current_price:
            rejected.append("PROMOTIONAL_PRICE_MUST_BE_LOWER")

        safety_blocked = set(rejected) - {"POSITIVE_PROFIT_IMPACT_UNSUPPORTED"}
        safety_missing = set(missing) - {
            "FRESH_MARKET_EVIDENCE_UNAVAILABLE",
            "PROFIT_FORECAST_UNSUPPORTED",
        }
        safety: Safety = (
            "blocked"
            if safety_blocked
            else "unavailable"
            if safety_missing
            else "verified"
        )
        return _Checks(tuple(missing), tuple(rejected), safety, proof)

    def _check_reorder(
        self,
        candidate: RecommendationCandidate,
        context: RecommendationDecisionContext,
        params: ReorderParameters,
        missing: list[str],
        rejected: list[str],
    ) -> None:
        snapshot = candidate.evidence.snapshot
        stock = context.inventory
        if (
            stock is None
            or candidate.evidence.inputs.get(EvidenceSource.INVENTORY_SNAPSHOT)
            != stock.snapshot_id
        ):
            missing.append("REORDER_INVENTORY_UNVERIFIED")
        if context.supplier_lead_time_days is None or (
            not (context.sales.rate is not None and context.sales.rate > ZERO)
            and not _has_approved_reorder_forecast(candidate, context)
        ):
            missing.append("REORDER_DEMAND_OR_LEAD_TIME_UNAVAILABLE")
        if params.deadline is None:
            missing.append("REORDER_DEADLINE_UNAVAILABLE")
        elif (
            params.deadline - context.business_date
        ).days > self.policy.reorder_horizon_days:
            rejected.append("REORDER_DEADLINE_OUTSIDE_HORIZON")
        if params.quantity is None or params.quantity <= 0:
            rejected.append("INVALID_REORDER_QUANTITY")
            return
        if snapshot.get("planning_method") == FORECAST_REORDER_VERSION:
            max_units = _object(snapshot.get("order_limits")).get("max_order_units")
            if type(max_units) is not int or max_units < 0:
                missing.append("REORDER_ORDER_LIMIT_UNVERIFIED")
            elif params.quantity > max_units:
                rejected.append("REORDER_ORDER_LIMIT_EXCEEDED")
        for key, code, violated in (
            (
                "minimum_order_quantity",
                "REORDER_MINIMUM_ORDER_VIOLATION",
                lambda constraint: params.quantity < constraint,
            ),
            (
                "pack_size",
                "REORDER_PACK_SIZE_VIOLATION",
                lambda constraint: params.quantity % constraint != 0,
            ),
        ):
            limit = snapshot.get(key)
            if key not in snapshot or (
                limit is not None and (type(limit) is not int or limit <= 0)
            ):
                missing.append("REORDER_SELLER_CONSTRAINTS_UNVERIFIED")
            elif isinstance(limit, int) and violated(limit):
                rejected.append(code)

    def _factors(
        self,
        candidate: RecommendationCandidate,
        context: RecommendationDecisionContext,
        checks: _Checks,
        recovery: dict[str, object],
        *,
        score: bool,
        benefit_supported: bool,
    ) -> tuple[EvaluationFactor, ...]:
        policy = self.policy
        params = candidate.proposed_parameters
        factors: list[EvaluationFactor] = []

        def add(
            name: str,
            raw: Decimal | None,
            unit: str,
            source: str,
            provenance: Provenance,
            normalized: Decimal | None = None,
            weight: Decimal = ZERO,
        ) -> None:
            factors.append(
                EvaluationFactor(
                    name=name,
                    provenance=provenance if raw is not None else "unsupported",
                    source=source,
                    raw_value=raw,
                    unit=unit,
                    normalized=_normalize(normalized)
                    if score and normalized is not None
                    else None,
                    weight=weight,
                )
            )

        add(
            "available_inventory",
            Decimal(context.inventory.available_units) if context.inventory else None,
            "units",
            "inventory_snapshot_after_reservations",
            "measured",
        )
        add(
            "net_sales_rate",
            context.sales.rate,
            "units_per_day",
            context.sales.status,
            "measured"
            if context.sales.status == "OBSERVED"
            else "deterministic_estimate",
        )
        add(
            "engine_signal",
            candidate.confidence,
            "points_out_of_100",
            candidate.source_engine.value,
            "deterministic_estimate",
        )
        if candidate_price(candidate) is not None:
            add(
                "safe_price_floor",
                _number((checks.guard or {}).get("minimum_safe_price")),
                "BDT",
                "margin_guard",
                "deterministic_estimate",
            )
            add(
                "unit_contribution",
                _number((checks.guard or {}).get("unit_profit"))
                if checks.financial_safety == "verified"
                else None,
                "BDT_per_unit",
                "margin_guard",
                "deterministic_estimate",
            )
        impact = candidate.estimated_financial_impact
        profit = (
            impact.profit_delta
            if impact
            and benefit_supported
            and _supported_price_response(candidate, context)
            else None
        )
        add(
            "profit_delta",
            profit,
            "BDT",
            "historical_elasticity_scenario",
            "model_prediction",
            profit / policy.profit_reference_bdt if profit is not None else None,
            policy.benefit_weight,
        )
        feasibility = ONE
        if isinstance(params, PricingParameters):
            matches = (
                Decimal(context.validated_competitor_price_count)
                if context.competitors.scrape_run_id
                else None
            )
            total = len(context.competitors.observations)
            add(
                "market_quality",
                matches,
                "matched_prices",
                "validated_scrape_observations",
                "measured",
                matches / total if matches is not None and total else None,
                policy.evidence_weight,
            )
        elif isinstance(params, ReorderParameters):
            sales = context.sales
            sample = Decimal(sales.sample_days) if sales.rate is not None else None
            coverage = (
                ONE
                if sales.status == "OBSERVED"
                else sample / sales.window_days
                if sample is not None
                else None
            )
            add(
                "sales_evidence_quality",
                sample,
                "sales_days",
                sales.status,
                "measured",
                coverage,
                policy.evidence_weight,
            )
            if params.deadline is not None:
                days = Decimal(max(0, (params.deadline - context.business_date).days))
                add(
                    "reorder_urgency",
                    days,
                    "days",
                    "engine_reorder_deadline",
                    "deterministic_estimate",
                    ONE - days / max(1, policy.reorder_horizon_days),
                    policy.urgency_weight,
                )
            snapshot = candidate.evidence.snapshot
            deficit, target = (
                _number(snapshot.get("raw_reorder_quantity")),
                _number(snapshot.get("target_stock")),
            )
            add(
                "stock_gap",
                deficit,
                "units",
                "engine_unrounded_replenishment_gap",
                "deterministic_estimate",
                deficit / target
                if deficit is not None and target is not None and target > ZERO
                else None,
                policy.benefit_weight,
            )
        else:
            checked_assessment = (
                context.dead_stock_assessment_id is not None
                and candidate.evidence.inputs.get(EvidenceSource.DEAD_STOCK_ASSESSMENT)
                == context.dead_stock_assessment_id
            )
            add(
                "assessment_evidence",
                ONE if checked_assessment else None,
                "provenance_check",
                "scoped_recovery_assessment",
                "deterministic_estimate",
                ONE if checked_assessment else None,
                policy.evidence_weight,
            )
            risk_score = _number(
                _object(candidate.evidence.snapshot.get("inputs")).get("risk_score")
            )
            add(
                "recovery_urgency",
                risk_score,
                "points_out_of_100",
                "dead_stock_risk_rules",
                "deterministic_estimate",
                risk_score / 100 if risk_score is not None else None,
                policy.urgency_weight,
            )
            if params.action in {
                DeadStockRecoveryAction.DISCOUNT,
                DeadStockRecoveryAction.FLASH_SALE,
                DeadStockRecoveryAction.MANUAL_REVIEW,
            } or (
                params.action == DeadStockRecoveryAction.BUNDLE
                and recovery.get("companion_selection_requires_manual_review") is True
            ):
                feasibility = Decimal("0.5")
        add(
            "operational_feasibility",
            feasibility if score else None,
            "policy_points",
            "verified_operational_constraints",
            "deterministic_estimate",
            feasibility,
            policy.feasibility_weight,
        )

        risk = candidate.forecast_risk
        if risk:
            interval = risk.interval
            width = (
                (interval.upper - interval.lower) / (2 * abs(interval.central))
                if interval and interval.central != 0
                else None
            )
            probability = risk.adverse_outcome_probability
            downside = max(
                (item for item in (width, probability) if item is not None),
                default=None,
            )
            add(
                "forecast_uncertainty",
                downside,
                "ratio",
                risk.source,
                "deterministic_estimate"
                if interval
                and interval.kind == "sensitivity_band"
                and probability is None
                else "model_prediction",
                ONE - downside if downside is not None else None,
                policy.uncertainty_weight,
            )
        else:
            add(
                "forecast_uncertainty",
                None,
                "ratio",
                "unavailable",
                "unsupported",
                weight=policy.uncertainty_weight,
            )
        return tuple(factors)


def _has_approved_reorder_forecast(
    candidate: RecommendationCandidate, context: RecommendationDecisionContext
) -> bool:
    evidence = candidate.evidence.snapshot
    if evidence.get("planning_method") != FORECAST_REORDER_VERSION:
        return False
    try:
        forecast = ForecastInferenceResult.model_validate(evidence.get("forecast"))
    except ValidationError:
        return False
    demand = forecast.forecast.expected_units
    uncertainty = _object(evidence.get("uncertainty"))
    return (
        approved_reorder_forecast(
            forecast,
            seller_id=context.seller_id,
            product_id=context.product_id,
            lead_days=context.supplier_lead_time_days,
            business_date=context.business_date,
            evaluated_at=context.evaluated_at,
        )
        and demand is not None
        and (
            demand > 0 or uncertainty.get("status") == "validated_lead_time_upper_bound"
        )
    )


def candidate_price(candidate: RecommendationCandidate) -> Decimal | None:
    params = candidate.proposed_parameters
    if isinstance(params, PricingParameters):
        return params.target_price
    if isinstance(params, RecoveryParameters):
        return params.promotional_price
    return None


def _supported_price_response(
    candidate: RecommendationCandidate, context: RecommendationDecisionContext
) -> bool:
    selected = _object(candidate.evidence.snapshot.get("selected"))
    units = _number(selected.get("expected_units"))
    return (
        isinstance(candidate.proposed_parameters, PricingParameters)
        and candidate.proposed_parameters.target_price is not None
        and context.elasticity_observation_end is not None
        and context.elasticity_observation_end <= context.sales.through
        and (
            context.elasticity_estimate_id is None
            or candidate.evidence.inputs.get(EvidenceSource.ELASTICITY_ESTIMATE)
            == context.elasticity_estimate_id
        )
        and selected.get("forecast_method")
        == DemandEstimationMethod.HISTORICAL_ELASTICITY.value
        and units is not None
        and units >= ZERO
        and _number(selected.get("expected_profit")) is not None
    )


def _price_proof(candidate: RecommendationCandidate) -> dict[str, object]:
    if isinstance(candidate.proposed_parameters, PricingParameters):
        return _object(
            _object(candidate.evidence.snapshot.get("selected")).get("margin_guard")
        )
    return _object(_recovery_evidence(candidate).get("margin_guard"))


def _recovery_evidence(candidate: RecommendationCandidate) -> dict[str, object]:
    params = candidate.proposed_parameters
    raw = candidate.evidence.snapshot.get("candidate_actions")
    if isinstance(params, RecoveryParameters) and isinstance(raw, list) and raw:
        primary = _object(raw[0])
        if primary.get("action") == params.action.value:
            return _object(primary.get("evidence"))
    return {}


def _object(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _number(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str, float)):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def _normalize(value: Decimal) -> Decimal:
    return max(ZERO, min(ONE, value))
