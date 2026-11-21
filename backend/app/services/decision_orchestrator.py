"""Evaluate specialized recommendations and select compatible advisory actions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.metrics import (
    PricingConfig,
    compute_availability_counts,
    score_pricing_pressure,
)
from app.core.config import settings
from app.models.dead_stock_assessment import (
    DeadStockAssessment,
    DeadStockClassification,
    DeadStockDataStatus,
)
from app.models.demand_elasticity_estimate import (
    DemandElasticityEstimate,
    DemandEstimateDataStatus,
    DemandEstimationMethod,
)
from app.models.inventory_history import InventoryHistory
from app.models.pricing_analytics_snapshot import PricingAnalyticsDataStatus
from app.models.product import Product
from app.models.recommendation import RecommendationAction
from app.models.stockout_prediction import StockoutPrediction
from app.repositories.dead_stock_recovery_repository import DeadStockRecoveryRepository
from app.schemas.pricing_policy import (
    MarketplaceFeePolicyResponse,
    PricingPolicyResponse,
)
from app.schemas.recommendation_candidate import (
    MAX_PERSISTED_PRICE,
    CandidateEngine,
    CandidateStatus,
    RecommendationCandidate,
    RecoveryParameters,
    ReorderParameters,
)
from app.schemas.recommendation_decision import (
    DecisionInventory,
    DecisionSales,
    RecommendationDecisionContext,
)
from app.scraper.constants import MARKETPLACE_NAME
from app.services.action_evaluation_service import (
    PRICE_ACTIONS,
    STOCK_RECOVERY,
    ActionEvaluationService,
    candidate_price,
)
from app.services.dead_stock_recovery_service import (
    DeadStockRecoveryService,
    recovery_is_restricted,
)
from app.services.demand_response_service import DemandElasticityResult
from app.services.dynamic_pricing_service import (
    DynamicPricingService,
    PricingSalesBaseline,
    elasticity_from_record,
)
from app.services.margin_guard import MarginGuard
from app.services.pricing_analytics_service import money, percentile
from app.services.pricing_policy_service import PricingPolicyService
from app.services.recommendation_business_signals import (
    DemandInventoryEvidence,
    RecommendationBusinessSignals,
)
from app.services.recommendation_candidate_adapter import (
    SpecializedRecommendation,
    to_recommendation_candidate,
)
from app.services.recommendation_evidence_service import (
    MarketCompetitor,
    RecommendationEvidence,
)
from app.services.recommendation_evidence_validator import (
    RecommendationEvidenceValidator,
)
from app.services.reorder_recommendation_service import ReorderRecommendationService
from app.services.stockout_prediction_service import StockoutPredictionService
from app.services.recommendation_selection import (
    EngineEvaluation,
    RecommendationDecision,
    before_selection,
    reject_candidate,
    select_decision,
)

logger = logging.getLogger(__name__)
RECOVERY_CLASSES = {
    DeadStockClassification.SLOW_MOVING,
    DeadStockClassification.AT_RISK,
    DeadStockClassification.DEAD_STOCK,
}
POLICIES = tuple[PricingPolicyResponse, MarketplaceFeePolicyResponse]


@dataclass(frozen=True)
class PricingForecast:
    estimate: DemandElasticityResult
    calculated_at: datetime
    record_id: UUID | None


@dataclass(frozen=True)
class _PricingInputs:
    current_price: Decimal
    minimum_safe_price: Decimal
    competitor_min_price: Decimal
    competitor_q1_price: Decimal
    competitor_median_price: Decimal
    competitor_q3_price: Decimal
    competitor_max_price: Decimal
    confidence_score: Decimal
    inventory_risk_level: str | None
    data_status: PricingAnalyticsDataStatus = PricingAnalyticsDataStatus.SUFFICIENT
    recent_net_sales: int | None = None
    id: UUID | None = None


class DecisionOrchestrator:
    def __init__(
        self,
        db: Session,
        *,
        forecast_provider: Callable[[UUID, UUID], PricingForecast | None] | None = None,
    ) -> None:
        self._db = db
        self._evaluator = (
            ActionEvaluationService()
            if settings.recommendation_action_evaluation_enabled
            else None
        )
        self._policy_service = PricingPolicyService(db)
        self._inventory_signals = RecommendationBusinessSignals(db)
        self._recovery_repository = DeadStockRecoveryRepository(db)
        self._forecast_provider = forecast_provider or self._load_forecast

    def evaluate(
        self, product: Product, evidence: RecommendationEvidence
    ) -> RecommendationDecision:
        now = evidence.evaluated_at
        market = RecommendationEvidenceValidator(MarginGuard(self._db)).market(
            product, evidence, now
        )
        measured = self._inventory_signals.measure_inventory(product, now)
        if (
            measured.seller.id,
            measured.velocity.seller_id,
            measured.velocity.product_id,
        ) != (
            product.seller_id,
            product.seller_id,
            product.id,
        ):
            raise ValueError("Sales evidence must match the decision scope.")
        policy = self._resolve_policy(product, now)
        scope = {"seller_id": product.seller_id, "product_id": product.id}
        forecast = (
            None
            if settings.forecast_assisted_pricing_enabled
            else self._forecast_provider(product.seller_id, product.id)
        )
        assessment = self._recovery_repository.latest_assessment(**scope)
        if assessment is not None and (assessment.seller_id, assessment.product_id) != (
            product.seller_id,
            product.id,
        ):
            raise ValueError("Recovery assessment must match the decision scope.")
        inventory = _inventory_snapshot(measured.inventory, product)
        context = RecommendationDecisionContext(
            **scope,
            evaluated_at=now,
            business_date=measured.business_date,
            product_updated_at=product.updated_at,
            current_price=product.selling_price,
            unit_cost=product.cost_price,
            on_hand_units=product.stock_quantity,
            supplier_lead_time_days=measured.lead_time,
            policy=policy[0] if policy else None,
            effective_fees=policy[1] if policy and not policy[1].is_default else None,
            inventory=inventory,
            sales=DecisionSales(
                through=measured.velocity.as_of_date,
                version=measured.velocity.calculation_version,
                status=measured.demand_status,
                rate=measured.rate,
                coverage_id=measured.coverage.id if measured.coverage else None,
                valid_records=int(
                    str(measured.velocity.metadata.get("valid_sales_records", 0))
                ),
                sample_days=measured.velocity.sales_days,
                window_days=measured.velocity.window_days,
            ),
            competitors=evidence,
            validated_competitor_price_count=len(market),
            quality_flags=tuple(
                dict.fromkeys((*evidence.quality_flags, *measured.reason_codes))
            ),
            elasticity_estimate_id=forecast.record_id if forecast else None,
            elasticity_observation_end=forecast.estimate.observation_end
            if forecast
            else None,
            dead_stock_assessment_id=assessment.id if assessment else None,
            dead_stock_assessed_at=assessment.assessed_at if assessment else None,
        )
        guard = MarginGuard(self._db, resolved_policy=policy)
        stockout = (
            StockoutPredictionService(self._db).build_prediction(
                product=product,
                seller=measured.seller,
                inventory_snapshot=measured.inventory,
                sales_velocity=measured.velocity,
                as_of_date=context.business_date,
                calculated_at=now,
                calculation_version=settings.stockout_prediction_calculation_version,
                confirmed_incoming_quantity=0,
            )
            if context.inventory and context.sales.rate is not None
            else None
        )
        reorder = self._reorder(product, context, measured, stockout)
        pricing = self._pricing(
            product, context, market, forecast, guard, measured, stockout
        )
        evaluations = (
            reorder,
            pricing,
            self._recovery(
                product,
                context,
                assessment,
                guard,
                measured=measured,
                prefer_listing=any(
                    item.candidate is not None
                    and item.candidate.evaluation_status == CandidateStatus.ELIGIBLE
                    and item.candidate.action_type
                    in PRICE_ACTIONS | {RecommendationAction.REORDER}
                    for item in (reorder, pricing)
                )
                if settings.evidence_driven_recovery_enabled
                else False,
            ),
        )
        return select_decision(
            context,
            evaluations,
            _analytics(context, measured, market),
            evaluator=self._evaluator,
        )

    def finalize(
        self,
        product: Product,
        decision: RecommendationDecision,
        *,
        at: datetime | None = None,
    ) -> RecommendationDecision:
        """Re-evaluate eligibility against refreshed inputs and exact prices before saving."""
        context = decision.context
        evaluator = (
            ActionEvaluationService(decision.action_policy)
            if decision.action_policy is not None
            else None
        )
        if (product.seller_id, product.id) != (context.seller_id, context.product_id):
            raise ValueError("Decision belongs to another seller or product.")
        now = at or datetime.now(timezone.utc)
        product_changed = (
            product.updated_at != context.product_updated_at
            or product.selling_price != context.current_price
            or product.cost_price != context.unit_cost
            or product.stock_quantity != context.on_hand_units
            or (product.supplier_lead_time or None) != context.supplier_lead_time_days
        )
        pending = tuple(before_selection(item) for item in decision.evaluations)
        eligible = [
            item.candidate
            for item in pending
            if item.candidate
            and item.candidate.evaluation_status == CandidateStatus.ELIGIBLE
        ]
        if product_changed:
            invalidated = tuple(
                reject_candidate(item, "PRODUCT_INPUTS_CHANGED")
                if item.candidate in eligible
                else item
                for item in pending
            )
            return select_decision(
                context,
                invalidated,
                _without_stock_metrics(decision.analytics),
                evaluator=evaluator,
                at=now,
            )
        if not eligible:
            return decision

        inventory = (
            _inventory_snapshot(
                self._inventory_signals.current_inventory(
                    product, context.business_date, now, refresh=True
                ),
                product,
            )
            if context.inventory
            and any(_needs_inventory(candidate) for candidate in eligible)
            else context.inventory
        )
        has_price = any(
            candidate_price(candidate) is not None for candidate in eligible
        )
        policy = self._resolve_policy(product, now) if has_price else None
        guard = MarginGuard(self._db, resolved_policy=policy)
        market = (
            RecommendationEvidenceValidator(guard).market(
                product, context.competitors, now
            )
            if any(candidate.action_type in PRICE_ACTIONS for candidate in eligible)
            else None
        )
        evaluations: list[EngineEvaluation] = []
        for item in pending:
            candidate = item.candidate
            if (
                candidate is None
                or candidate.evaluation_status != CandidateStatus.ELIGIBLE
            ):
                evaluations.append(item)
                continue
            if candidate.expires_at is not None and candidate.expires_at <= now:
                item = reject_candidate(item, "CANDIDATE_EXPIRED")
            elif _needs_inventory(candidate) and inventory != context.inventory:
                item = reject_candidate(item, "INVENTORY_EVIDENCE_CHANGED")
            elif (
                candidate.source_engine == CandidateEngine.DEAD_STOCK_RECOVERY
                and not _fresh(
                    context.dead_stock_assessed_at,
                    now,
                    _inventory_max_age(),
                )
            ):
                item = reject_candidate(item, "DEAD_STOCK_ASSESSMENT_STALE")
            elif (
                candidate.action_type in PRICE_ACTIONS
                and market is not None
                and len(market) < context.validated_competitor_price_count
            ):
                item = reject_candidate(item, "COMPETITOR_EVIDENCE_STALE")
            elif (price := candidate_price(candidate)) is not None:
                item = self._recheck_price(product, context, item, price, policy, guard)
            evaluations.append(item)
        analytics = (
            _without_stock_metrics(decision.analytics)
            if inventory != context.inventory
            else decision.analytics
        )
        if market is not None:
            analytics = {**analytics, **_market_metrics(context, market)}
        return select_decision(
            context, tuple(evaluations), analytics, evaluator=evaluator, at=now
        )

    def _resolve_policy(self, product: Product, at: datetime) -> POLICIES | None:
        try:
            return self._policy_service.resolve_for_product(
                product, marketplace=MARKETPLACE_NAME, as_of=at
            )
        except ValidationError:
            logger.warning(
                "invalid_recommendation_pricing_policy product_id=%s", product.id
            )
            return None

    def _load_forecast(
        self, seller_id: UUID, product_id: UUID
    ) -> PricingForecast | None:
        row = self._db.scalars(
            select(DemandElasticityEstimate)
            .where(
                DemandElasticityEstimate.seller_id == seller_id,
                DemandElasticityEstimate.product_id == product_id,
            )
            .order_by(
                DemandElasticityEstimate.calculated_at.desc(),
                DemandElasticityEstimate.id.desc(),
            )
            .limit(1)
        ).first()
        return (
            PricingForecast(elasticity_from_record(row), row.calculated_at, row.id)
            if row
            else None
        )

    @staticmethod
    def _recheck_price(
        product: Product,
        context: RecommendationDecisionContext,
        item: EngineEvaluation,
        price: Decimal,
        policy: POLICIES | None,
        guard: MarginGuard,
    ) -> EngineEvaluation:
        if policy is None:
            return reject_candidate(item, "INVALID_OR_MISSING_PRICING_POLICY")
        # A safe price under a changed fee schedule no longer has the originally
        # estimated economics. Preserve the guard result and reconsider the next candidate.
        result = guard.validate_candidate(
            seller_id=context.seller_id,
            product=product,
            candidate_price=price,
            marketplace=MARKETPLACE_NAME,
        )
        item = replace(item, guard=result.to_evidence())
        if not result.is_allowed or result.candidate_price != price:
            return reject_candidate(
                item,
                "MARGIN_GUARD_BLOCKED",
                *(reason.value for reason in result.rejection_reasons),
            )
        current_policy, current_fee = policy
        previous_policy = context.policy
        if (
            previous_policy is not None
            and current_policy.is_default
            and previous_policy.is_default
        ):
            # The synthesized default has no effective-date record. Its timestamp
            # reflects resolution time, while its economic terms remain comparable.
            current_policy = current_policy.model_copy(
                update={"effective_from": previous_policy.effective_from}
            )
        if current_policy != previous_policy or current_fee != context.effective_fees:
            return reject_candidate(item, "EFFECTIVE_PRICING_TERMS_CHANGED")
        return item

    def _reorder(
        self,
        product: Product,
        context: RecommendationDecisionContext,
        measured: DemandInventoryEvidence,
        stockout: StockoutPrediction | None,
    ) -> EngineEvaluation:
        engine = CandidateEngine.REORDER
        if recovery_is_restricted(product):
            return EngineEvaluation(
                engine, reason_codes=("PRODUCT_REQUIRES_MANUAL_REVIEW",)
            )
        forecast_enabled = settings.forecast_aware_reorder_enabled
        if not forecast_enabled and (
            context.inventory is None or context.supplier_lead_time_days is None
        ):
            return EngineEvaluation(engine, reason_codes=measured.reason_codes)
        row = ReorderRecommendationService(self._db).build_recommendation(
            product=product,
            seller=measured.seller,
            inventory_snapshot=measured.inventory,
            sales_velocity=measured.velocity
            if context.sales.rate is not None
            else None,
            stockout_prediction=stockout,
            as_of_date=context.business_date,
            generated_at=context.evaluated_at,
            calculation_version=settings.reorder_calculation_version,
            confirmed_incoming_quantity=None if forecast_enabled else 0,
            verified_zero_sales=context.sales.status == "OBSERVED"
            and context.sales.rate == 0,
        )
        evaluation = _adapt(engine, context, row)
        if forecast_enabled:
            evaluation = replace(
                evaluation,
                reason_codes=(*evaluation.reason_codes, *row.evidence["reason_codes"]),
            )
        if (
            evaluation.candidate
            and evaluation.candidate.action_type == RecommendationAction.REORDER
        ):
            params = evaluation.candidate.proposed_parameters
            if not isinstance(params, ReorderParameters) or params.deadline is None:
                return reject_candidate(evaluation, "REORDER_DEADLINE_UNAVAILABLE")
        return evaluation

    def _pricing(
        self,
        product: Product,
        context: RecommendationDecisionContext,
        market: list[MarketCompetitor],
        forecast: PricingForecast | None,
        guard: MarginGuard,
        measured: DemandInventoryEvidence,
        stockout: StockoutPrediction | None,
    ) -> EngineEvaluation:
        engine = CandidateEngine.DYNAMIC_PRICING
        if recovery_is_restricted(product):
            return EngineEvaluation(
                engine, reason_codes=("PRODUCT_REQUIRES_MANUAL_REVIEW",)
            )
        risk = None
        if (
            stockout
            and stockout.predicted_stockout_date is not None
            and context.supplier_lead_time_days is not None
            and stockout.predicted_stockout_date
            <= context.business_date + timedelta(days=context.supplier_lead_time_days)
        ):
            risk = "HIGH"
        if settings.forecast_assisted_pricing_enabled:
            row = DynamicPricingService(
                self._db, margin_guard=guard
            ).build_forecast_assisted_recommendation(
                product=product,
                market=context.competitors,
                policy=context.policy,
                inventory_risk=risk,
            )
            evaluation = _adapt(engine, context, row)
            return replace(
                evaluation,
                reason_codes=(
                    *evaluation.reason_codes,
                    *row.evidence["rejection_reasons"],
                ),
            )
        reasons = []
        if len(market) < PricingConfig().min_competitor_count:
            reasons.append("INSUFFICIENT_FRESH_COMPETITOR_PRICES")
        if (
            context.current_price is None
            or context.current_price <= 0
            or context.unit_cost is None
        ):
            reasons.append("MISSING_OR_INVALID_CURRENT_ECONOMICS")
        if context.effective_fees is None or context.policy is None:
            reasons.append("MISSING_FEE_POLICY")
        if (
            context.sales.rate is None
            or context.sales.rate <= 0
            or context.inventory is None
            or context.supplier_lead_time_days is None
        ):
            reasons.append("INSUFFICIENT_PRICING_DEMAND_OR_INVENTORY")
        if not _supported_forecast(context, forecast):
            reasons.append("INSUFFICIENT_PRICE_RESPONSE_EVIDENCE")
        if reasons:
            return EngineEvaluation(engine, reason_codes=tuple(reasons))

        assert (
            context.current_price is not None
            and context.policy is not None
            and context.sales.rate is not None
            and forecast is not None
        )
        baseline = guard.validate_candidate(
            seller_id=context.seller_id,
            product=product,
            candidate_price=context.current_price,
            marketplace=MARKETPLACE_NAME,
        )
        if baseline.minimum_safe_price is None or baseline.unit_profit is None:
            return EngineEvaluation(
                engine,
                reason_codes=tuple(
                    reason.value for reason in baseline.rejection_reasons
                )
                or ("BASELINE_ECONOMICS_UNAVAILABLE",),
            )
        prices = sorted(item["price"] for item in market)
        inputs = _PricingInputs(
            current_price=context.current_price,
            minimum_safe_price=baseline.minimum_safe_price,
            competitor_min_price=prices[0],
            competitor_q1_price=money(percentile(prices, Decimal("0.25"))),
            competitor_median_price=money(percentile(prices, Decimal("0.5"))),
            competitor_q3_price=money(percentile(prices, Decimal("0.75"))),
            competitor_max_price=prices[-1],
            confidence_score=measured.velocity.confidence_score,
            inventory_risk_level=risk,
        )
        row = DynamicPricingService(
            self._db,
            margin_guard=guard,
            include_evaluation_evidence=self._evaluator is not None,
        ).build_recommendation(
            seller_id=context.seller_id,
            product=product,
            analytics=inputs,
            estimate=forecast.estimate,
            objective=context.policy.objective,
            elasticity_estimate_id=forecast.record_id,
            generated_at=context.evaluated_at,
            cooldown_hours=context.policy.recommendation_cooldown_hours,
            price_increment=context.policy.price_increment,
            sales_baseline=PricingSalesBaseline(
                daily_rate=context.sales.rate,
                recorded_net_units=measured.velocity.net_units_sold,
                window_days=context.sales.window_days,
                through=context.sales.through,
                complete=context.sales.status == "OBSERVED",
            ),
        )
        evaluation = _adapt(engine, context, row)
        candidate = evaluation.candidate
        if (
            candidate
            and candidate.evaluation_status == CandidateStatus.ELIGIBLE
            and candidate.action_type in PRICE_ACTIONS
        ):
            target = candidate_price(candidate)
            if target is None or target > MAX_PERSISTED_PRICE:
                return reject_candidate(evaluation, "PRICE_OUTSIDE_SUPPORTED_RANGE")
            if context.inventory is None or context.inventory.available_units == 0:
                return reject_candidate(evaluation, "NO_SELLABLE_INVENTORY")
            impact = candidate.estimated_financial_impact
            if (
                impact is None
                or impact.profit_delta is None
                or impact.profit_delta <= 0
            ):
                return reject_candidate(
                    evaluation, "POSITIVE_PROFIT_IMPACT_UNSUPPORTED"
                )
            if risk == "HIGH" and candidate.action_type == RecommendationAction.LOWER:
                return reject_candidate(
                    evaluation, "LOWER_CONFLICTS_WITH_NEAR_TERM_STOCKOUT"
                )
        return evaluation

    def _recovery(
        self,
        product: Product,
        context: RecommendationDecisionContext,
        assessment: DeadStockAssessment | None,
        guard: MarginGuard,
        *,
        measured: DemandInventoryEvidence | None = None,
        prefer_listing: bool = False,
    ) -> EngineEvaluation:
        engine = CandidateEngine.DEAD_STOCK_RECOVERY
        if assessment is None:
            return EngineEvaluation(
                engine, reason_codes=("DEAD_STOCK_ASSESSMENT_MISSING",)
            )
        if not settings.evidence_driven_recovery_enabled and (
            not _fresh(
                assessment.assessed_at, context.evaluated_at, _inventory_max_age()
            )
            or assessment.as_of_date > context.business_date
            or context.business_date - assessment.as_of_date
            > _inventory_max_age() + timedelta(days=1)
            or assessment.data_status == DeadStockDataStatus.INSUFFICIENT
            or assessment.classification == DeadStockClassification.INSUFFICIENT_DATA
        ):
            return EngineEvaluation(
                engine, reason_codes=("DEAD_STOCK_ASSESSMENT_STALE_OR_INSUFFICIENT",)
            )

        scope = {"seller_id": context.seller_id, "product_id": context.product_id}
        relevant = assessment.classification in RECOVERY_CLASSES
        visibility = (
            self._recovery_repository.visibility_for_product(
                **scope, as_of_date=assessment.as_of_date
            )
            if relevant
            else None
        )
        if visibility and (
            visibility["marketplace"] != MARKETPLACE_NAME
            or context.business_date - date.fromisoformat(visibility["metric_date"])
            > _inventory_max_age() + timedelta(days=1)
        ):
            visibility = None
        companions = (
            self._recovery_repository.companion_products(
                seller_id=context.seller_id, product=product
            )
            if relevant and not settings.evidence_driven_recovery_enabled
            else []
        )
        row = DeadStockRecoveryService(
            self._db, margin_guard_factory=lambda _: guard
        ).build_recommendation(
            product=product,
            assessment=assessment,
            aging=self._recovery_repository.latest_aging(
                **scope, as_of_date=assessment.as_of_date
            )
            if relevant and settings.evidence_driven_recovery_enabled
            else None,
            velocity=measured.velocity
            if settings.evidence_driven_recovery_enabled
            and measured is not None
            and context.sales.rate is not None
            else None,
            visibility=visibility,
            promotion_history=[],
            bundle_data=[],
            companion_products=companions,
            generated_at=context.evaluated_at,
            inventory=measured.inventory
            if settings.evidence_driven_recovery_enabled and measured is not None
            else None,
            prefer_listing=prefer_listing,
        )
        evaluation = _adapt(engine, context, row)
        candidate = evaluation.candidate
        if candidate and candidate.evaluation_status == CandidateStatus.ELIGIBLE:
            params = candidate.proposed_parameters
            if (
                isinstance(params, RecoveryParameters)
                and params.action in STOCK_RECOVERY
                and (
                    context.inventory is None
                    or not params.quantity
                    or params.quantity > context.inventory.available_units
                    or assessment.inventory_snapshot_id != context.inventory.snapshot_id
                )
            ):
                return reject_candidate(evaluation, "RECOVERY_QUANTITY_UNSUPPORTED")
        return evaluation


def _adapt(
    engine: CandidateEngine,
    context: RecommendationDecisionContext,
    row: SpecializedRecommendation,
) -> EngineEvaluation:
    try:
        candidate = to_recommendation_candidate(
            row, seller_id=context.seller_id, product_id=context.product_id
        )
    except ValidationError:
        logger.warning(
            "invalid_specialized_candidate engine=%s product_id=%s",
            engine.value,
            context.product_id,
        )
        return EngineEvaluation(engine, reason_codes=("INVALID_SPECIALIZED_OUTPUT",))
    return EngineEvaluation(engine, candidate)


def _needs_inventory(candidate: RecommendationCandidate) -> bool:
    params = candidate.proposed_parameters
    return (
        candidate.action_type in PRICE_ACTIONS
        or candidate.source_engine == CandidateEngine.REORDER
        or (isinstance(params, RecoveryParameters) and params.action in STOCK_RECOVERY)
    )


def _fresh(timestamp: datetime | None, now: datetime, max_age: timedelta) -> bool:
    return (
        timestamp is not None
        and timestamp.utcoffset() is not None
        and timedelta(0) <= now - timestamp <= max_age
    )


def _inventory_max_age() -> timedelta:
    return timedelta(hours=settings.recommendation_inventory_max_age_hours)


def _inventory_snapshot(
    row: InventoryHistory | None, product: Product
) -> DecisionInventory | None:
    if row is None:
        return None
    if (row.seller_id, row.product_id) != (product.seller_id, product.id):
        raise ValueError("Inventory must match the decision scope.")
    return DecisionInventory(
        snapshot_id=row.id,
        captured_at=row.captured_at,
        on_hand_units=row.quantity_on_hand,
        reserved_units=row.quantity_reserved,
        available_units=max(0, row.quantity_available),
    )


def _supported_forecast(
    context: RecommendationDecisionContext, forecast: PricingForecast | None
) -> bool:
    if forecast is None:
        return False
    estimate = forecast.estimate
    age = settings.demand_response_max_data_age_days
    return (
        estimate.method == DemandEstimationMethod.HISTORICAL_ELASTICITY
        and estimate.data_status == DemandEstimateDataStatus.SUFFICIENT
        and estimate.elasticity is not None
        and estimate.elasticity.is_finite()
        and Decimal(str(settings.demand_response_min_elasticity))
        <= estimate.elasticity
        <= Decimal(str(settings.demand_response_max_elasticity))
        and estimate.observation_end is not None
        and 0 <= (context.sales.through - estimate.observation_end).days <= age
        and _fresh(forecast.calculated_at, context.evaluated_at, timedelta(days=age))
    )


def _analytics(
    context: RecommendationDecisionContext,
    measured: DemandInventoryEvidence,
    market: list[MarketCompetitor],
) -> dict[str, Any]:
    risk = measured.stock_risk
    return {
        "decision_orchestration_version": 1,
        **_market_metrics(context, market),
        "estimated_days_of_stock_left": round(float(measured.days_left), 2)
        if measured.days_left is not None
        else None,
        "stock_risk_score": risk,
        "urgency_score": risk,
        "inventory_evidence": measured.to_context(),
    }


def _market_metrics(
    context: RecommendationDecisionContext,
    market: list[MarketCompetitor],
) -> dict[str, Any]:
    prices = sorted(item["price"] for item in market)
    midpoint = percentile(prices, Decimal("0.5")) if prices else None
    current = context.current_price
    gap = float((current - midpoint) * 100 / midpoint) if current and midpoint else None
    counts = compute_availability_counts(item["stock_status"] for item in market)
    return {
        "competitor_median_price": str(midpoint) if midpoint is not None else None,
        "price_gap_percent": gap,
        "pricing_pressure_score": (
            round(
                score_pricing_pressure(
                    gap, PricingConfig().pricing_pressure_reference_percent
                ),
                2,
            )
            if gap is not None
            else None
        ),
        "out_of_stock_competitor_count": counts["out_of_stock"]
        if counts["total"]
        else None,
        "competitor_availability_ratio": counts["ratio"] if counts["total"] else None,
    }


def _without_stock_metrics(analytics: dict[str, Any]) -> dict[str, Any]:
    return {
        **analytics,
        "stock_risk_score": None,
        "urgency_score": None,
        "estimated_days_of_stock_left": None,
    }
