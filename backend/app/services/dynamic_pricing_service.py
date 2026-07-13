from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.demand_elasticity_estimate import DemandElasticityEstimate, DemandEstimationMethod
from app.models.dynamic_pricing_recommendation import DynamicPricingAction, DynamicPricingRecommendation, DynamicPricingRecommendationStatus
from app.models.pricing_analytics_snapshot import PricingAnalyticsDataStatus, PricingAnalyticsSnapshot
from app.models.pricing_policy import PricingObjective
from app.models.product import Product
from app.models.rag_memory import RagMemorySourceType
from app.services.demand_response_service import DemandElasticityResult, DemandResponseService
from app.services.margin_guard import MarginGuard
from app.services.pricing_policy_service import PricingPolicyService
from app.services.rag_index_outbox_service import RagIndexOutboxService

MONEY = Decimal("0.01")


@dataclass(frozen=True)
class DynamicPricingConfig:
    formula_version: str
    min_improvement_rate: Decimal
    min_actionable_change_rate: Decimal
    max_change_rate: Decimal
    expiration_hours: int

    @classmethod
    def from_settings(cls) -> "DynamicPricingConfig":
        return cls(
            formula_version=settings.dynamic_pricing_formula_version,
            min_improvement_rate=Decimal(str(settings.dynamic_pricing_min_improvement_rate)),
            min_actionable_change_rate=Decimal(str(settings.dynamic_pricing_min_actionable_change_rate)),
            max_change_rate=Decimal(str(settings.dynamic_pricing_max_change_rate)),
            expiration_hours=settings.dynamic_pricing_expiration_hours,
        )


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_price: Decimal
    is_allowed: bool
    expected_units: Decimal | None
    expected_revenue: Decimal | None
    expected_profit: Decimal | None
    margin_rate: Decimal | None
    score: Decimal
    confidence_score: Decimal
    rejection_reasons: list[str]
    evidence: dict[str, object]


class DynamicPricingService:
    def __init__(self, db: Session | None = None, *, config: DynamicPricingConfig | None = None) -> None:
        self._db = db
        self._config = config or DynamicPricingConfig.from_settings()

    def generate_for_product(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        generated_at: datetime | None = None,
    ) -> DynamicPricingRecommendation:
        if self._db is None:
            raise ValueError("A database session is required.")
        timestamp = _utc(generated_at or datetime.now(timezone.utc))
        product = self._product(seller_id=seller_id, product_id=product_id)
        analytics = self._latest_analytics(seller_id=seller_id, product_id=product_id)
        if analytics is None:
            raise ValueError("Pricing analytics snapshot is required.")
        policy = PricingPolicyService(self._db).get_product_policy(
            seller_id=seller_id,
            product_id=product_id,
            marketplace="Daraz Bangladesh",
        )
        objective = policy.objective if isinstance(policy.objective, PricingObjective) else PricingObjective(policy.objective)
        existing = self._existing_for_snapshot(
            seller_id=seller_id,
            product_id=product_id,
            pricing_analytics_id=analytics.id,
            objective=objective,
        )
        if existing:
            return existing
        cooldown = self._open_recent(seller_id=seller_id, product_id=product_id, objective=objective, timestamp=timestamp, hours=policy.recommendation_cooldown_hours)
        if cooldown:
            return cooldown

        estimate_record = self._latest_elasticity(seller_id=seller_id, product_id=product_id)
        estimate = _estimate_from_record(estimate_record) if estimate_record else DemandResponseService(self._db).estimate_for_product(
            seller_id=seller_id,
            product_id=product_id,
            as_of_date=timestamp.date(),
        )
        recommendation = self.build_recommendation(
            seller_id=seller_id,
            product=product,
            analytics=analytics,
            estimate=estimate,
            objective=objective,
            elasticity_estimate_id=estimate_record.id if estimate_record else None,
            generated_at=timestamp,
            cooldown_hours=policy.recommendation_cooldown_hours,
        )
        try:
            self._db.add(recommendation)
            self._db.flush()
            RagIndexOutboxService(self._db).enqueue_upsert(
                seller_id=seller_id,
                source_type=RagMemorySourceType.PRICE_HISTORY,
                source_id=str(recommendation.id),
                product_id=product_id,
                source_updated_at=timestamp,
            )
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self._existing_for_snapshot(
                seller_id=seller_id,
                product_id=product_id,
                pricing_analytics_id=analytics.id,
                objective=objective,
            )
            if existing:
                return existing
            raise
        self._db.refresh(recommendation)
        return recommendation

    def build_recommendation(
        self,
        *,
        seller_id: UUID,
        product,
        analytics,
        estimate: DemandElasticityResult,
        objective: PricingObjective,
        elasticity_estimate_id: UUID | None,
        generated_at: datetime,
        cooldown_hours: int,
    ) -> DynamicPricingRecommendation:
        current_price = _money(Decimal(str(analytics.current_price)))
        candidates = generate_candidates(
            current_price=current_price,
            minimum_safe_price=Decimal(str(analytics.minimum_safe_price)),
            competitor_values=[
                analytics.competitor_min_price,
                analytics.competitor_q1_price,
                analytics.competitor_median_price,
                analytics.competitor_q3_price,
                analytics.competitor_max_price,
            ],
            increment=Decimal("1.00"),
            max_change_rate=self._config.max_change_rate,
        )
        baseline_units = _baseline_units(analytics, estimate)
        baseline_guard = MarginGuard(self._db).validate_candidate(
            seller_id=seller_id,
            product=product,
            candidate_price=current_price,
        )
        baseline_units_value = baseline_units or Decimal("0")
        baseline_revenue = _money(current_price * baseline_units_value) if baseline_units is not None else None
        baseline_profit = _money((baseline_guard.unit_profit or Decimal("0")) * baseline_units_value) if baseline_units is not None else None
        evaluations = [
            self.evaluate_candidate(
                seller_id=seller_id,
                product=product,
                analytics=analytics,
                estimate=estimate,
                candidate_price=candidate,
                baseline_units=baseline_units,
                baseline_profit=baseline_profit,
                baseline_revenue=baseline_revenue,
                objective=objective,
            )
            for candidate in candidates
        ]
        allowed = [item for item in evaluations if item.is_allowed and item.expected_profit is not None and item.expected_revenue is not None]
        status = DynamicPricingRecommendationStatus.OPEN
        if analytics.data_status in {PricingAnalyticsDataStatus.INSUFFICIENT, PricingAnalyticsDataStatus.STALE} or estimate.elasticity is None:
            status = DynamicPricingRecommendationStatus.INSUFFICIENT_DATA
        selected = select_candidate(
            evaluations=allowed,
            current_price=current_price,
            objective=objective,
            min_improvement_rate=self._config.min_improvement_rate,
            baseline_profit=baseline_profit,
            baseline_revenue=baseline_revenue,
        )
        if selected is None:
            selected = next((item for item in evaluations if item.candidate_price == current_price), None) or evaluations[0]
        action = derive_action(
            current_price=current_price,
            selected_price=selected.candidate_price,
            min_actionable_change_rate=self._config.min_actionable_change_rate,
        )
        if status == DynamicPricingRecommendationStatus.INSUFFICIENT_DATA:
            action = DynamicPricingAction.HOLD
        evidence = {
            "formula_version": self._config.formula_version,
            "scoring": "profit objective uses expected_profit; revenue objective uses expected_revenue among margin-safe candidates; penalties subtract confidence, stale data, large changes, inventory risk, sparse data, and market distance.",
            "candidate_count": len(evaluations),
            "candidates": [item.evidence for item in evaluations],
            "selected": selected.evidence,
            "cooldown_hours": cooldown_hours,
            "demand_method": estimate.method.value,
            "heuristic_disclosure": estimate.evidence if estimate.method == DemandEstimationMethod.CONSERVATIVE_HEURISTIC else None,
        }
        return DynamicPricingRecommendation(
            seller_id=seller_id,
            product_id=product.id,
            pricing_analytics_id=analytics.id,
            elasticity_estimate_id=elasticity_estimate_id,
            action=action,
            current_price=current_price,
            recommended_price=selected.candidate_price,
            minimum_safe_price=selected.evidence.get("minimum_safe_price"),
            expected_units=selected.expected_units,
            expected_revenue=selected.expected_revenue,
            expected_profit=selected.expected_profit,
            baseline_expected_revenue=baseline_revenue,
            baseline_expected_profit=baseline_profit,
            revenue_impact=_money((selected.expected_revenue or Decimal("0")) - baseline_revenue) if baseline_revenue is not None and selected.expected_revenue is not None else None,
            profit_impact=_money((selected.expected_profit or Decimal("0")) - baseline_profit) if baseline_profit is not None and selected.expected_profit is not None else None,
            margin_rate=selected.margin_rate,
            confidence_score=selected.confidence_score if status == DynamicPricingRecommendationStatus.OPEN else Decimal("0.00"),
            estimation_method=estimate.method,
            recommendation_status=status,
            objective=objective,
            evidence=evidence,
            formula_version=self._config.formula_version,
            generated_at=generated_at,
            expires_at=generated_at + timedelta(hours=self._config.expiration_hours),
        )

    def evaluate_candidate(
        self,
        *,
        seller_id: UUID,
        product,
        analytics,
        estimate: DemandElasticityResult,
        candidate_price: Decimal,
        baseline_units: Decimal | None,
        baseline_profit: Decimal | None,
        baseline_revenue: Decimal | None,
        objective: PricingObjective,
    ) -> CandidateEvaluation:
        guard = MarginGuard(self._db).validate_candidate(seller_id=seller_id, product=product, candidate_price=candidate_price)
        forecast = DemandResponseService(config=DemandResponseService(self._db)._config).forecast_candidate_units(
            current_price=Decimal(str(analytics.current_price)),
            candidate_price=candidate_price,
            baseline_units=baseline_units or Decimal("0"),
            forecast_horizon_days=30,
            baseline_period={"source": "analytics_or_elasticity", "baseline_units": str(baseline_units) if baseline_units is not None else None},
            estimate=estimate,
        )
        expected_units = forecast.central_estimate if guard.is_allowed else None
        expected_revenue = _money(candidate_price * expected_units) if expected_units is not None else None
        expected_profit = _money((guard.unit_profit or Decimal("0")) * expected_units) if expected_units is not None else None
        penalties = calculate_penalties(candidate_price=candidate_price, analytics=analytics, estimate=estimate, forecast_confidence=forecast.confidence)
        base = expected_profit if objective == PricingObjective.MAXIMIZE_EXPECTED_PROFIT else expected_revenue
        score = (base or Decimal("0")) - penalties
        confidence = max(Decimal("0"), min(Decimal("100"), (forecast.confidence + Decimal(str(analytics.confidence_score))) / Decimal("2") - penalties / Decimal("100")))
        evidence = {
            "candidate_price": str(candidate_price),
            "is_allowed": guard.is_allowed,
            "rejection_reasons": [reason.value for reason in guard.rejection_reasons],
            "minimum_safe_price": str(guard.minimum_safe_price) if guard.minimum_safe_price is not None else None,
            "expected_units": str(expected_units) if expected_units is not None else None,
            "expected_revenue": str(expected_revenue) if expected_revenue is not None else None,
            "expected_profit": str(expected_profit) if expected_profit is not None else None,
            "score": str(_money(score)),
            "risk_penalty": str(_money(penalties)),
            "forecast_method": forecast.method.value,
            "forecast_confidence": str(forecast.confidence),
            "inventory_risk_level": analytics.inventory_risk_level,
        }
        return CandidateEvaluation(
            candidate_price=candidate_price,
            is_allowed=guard.is_allowed,
            expected_units=expected_units,
            expected_revenue=expected_revenue,
            expected_profit=expected_profit,
            margin_rate=guard.margin_rate,
            score=_money(score),
            confidence_score=_score(confidence),
            rejection_reasons=[reason.value for reason in guard.rejection_reasons],
            evidence=evidence,
        )

    def latest(self, *, seller_id: UUID, product_id: UUID) -> DynamicPricingRecommendation | None:
        self._product(seller_id=seller_id, product_id=product_id)
        return self._db.execute(select(DynamicPricingRecommendation).where(DynamicPricingRecommendation.seller_id == seller_id, DynamicPricingRecommendation.product_id == product_id).order_by(DynamicPricingRecommendation.generated_at.desc()).limit(1)).scalar_one_or_none()

    def list_product(self, *, seller_id: UUID, product_id: UUID, limit: int, offset: int) -> tuple[list[DynamicPricingRecommendation], int]:
        self._product(seller_id=seller_id, product_id=product_id)
        statement = select(DynamicPricingRecommendation).where(DynamicPricingRecommendation.seller_id == seller_id, DynamicPricingRecommendation.product_id == product_id)
        total = self._db.execute(select(DynamicPricingRecommendation.id).where(DynamicPricingRecommendation.seller_id == seller_id, DynamicPricingRecommendation.product_id == product_id)).all()
        items = self._db.execute(statement.order_by(DynamicPricingRecommendation.generated_at.desc()).limit(limit).offset(offset)).scalars().all()
        return items, len(total)

    def get(self, *, seller_id: UUID, recommendation_id: UUID) -> DynamicPricingRecommendation | None:
        return self._db.execute(select(DynamicPricingRecommendation).where(DynamicPricingRecommendation.seller_id == seller_id, DynamicPricingRecommendation.id == recommendation_id)).scalar_one_or_none()

    def update_status(self, *, seller_id: UUID, recommendation_id: UUID, status: DynamicPricingRecommendationStatus) -> DynamicPricingRecommendation:
        item = self.get(seller_id=seller_id, recommendation_id=recommendation_id)
        if item is None:
            raise ValueError("Recommendation not found.")
        now = datetime.now(timezone.utc)
        item.recommendation_status = status
        if status == DynamicPricingRecommendationStatus.ACKNOWLEDGED:
            item.acknowledged_at = now
        if status == DynamicPricingRecommendationStatus.DISMISSED:
            item.dismissed_at = now
        RagIndexOutboxService(self._db).enqueue_upsert(
            seller_id=seller_id,
            source_type=RagMemorySourceType.PRICE_HISTORY,
            source_id=str(item.id),
            product_id=item.product_id,
            source_updated_at=now,
        )
        self._db.commit()
        self._db.refresh(item)
        return item

    def _product(self, *, seller_id: UUID, product_id: UUID) -> Product:
        product = self._db.execute(select(Product).where(Product.seller_id == seller_id, Product.id == product_id)).scalar_one_or_none()
        if product is None:
            raise ValueError("Product not found.")
        return product

    def _latest_analytics(self, *, seller_id: UUID, product_id: UUID) -> PricingAnalyticsSnapshot | None:
        return self._db.execute(select(PricingAnalyticsSnapshot).where(PricingAnalyticsSnapshot.seller_id == seller_id, PricingAnalyticsSnapshot.product_id == product_id).order_by(PricingAnalyticsSnapshot.calculated_at.desc()).limit(1)).scalar_one_or_none()

    def _latest_elasticity(self, *, seller_id: UUID, product_id: UUID) -> DemandElasticityEstimate | None:
        return self._db.execute(select(DemandElasticityEstimate).where(DemandElasticityEstimate.seller_id == seller_id, DemandElasticityEstimate.product_id == product_id).order_by(DemandElasticityEstimate.calculated_at.desc()).limit(1)).scalar_one_or_none()

    def _existing_for_snapshot(self, *, seller_id: UUID, product_id: UUID, pricing_analytics_id: UUID, objective: PricingObjective) -> DynamicPricingRecommendation | None:
        return self._db.execute(select(DynamicPricingRecommendation).where(DynamicPricingRecommendation.seller_id == seller_id, DynamicPricingRecommendation.product_id == product_id, DynamicPricingRecommendation.pricing_analytics_id == pricing_analytics_id, DynamicPricingRecommendation.objective == objective, DynamicPricingRecommendation.formula_version == self._config.formula_version)).scalar_one_or_none()

    def _open_recent(self, *, seller_id: UUID, product_id: UUID, objective: PricingObjective, timestamp: datetime, hours: int) -> DynamicPricingRecommendation | None:
        cutoff = timestamp - timedelta(hours=hours)
        return self._db.execute(select(DynamicPricingRecommendation).where(DynamicPricingRecommendation.seller_id == seller_id, DynamicPricingRecommendation.product_id == product_id, DynamicPricingRecommendation.objective == objective, DynamicPricingRecommendation.formula_version == self._config.formula_version, DynamicPricingRecommendation.recommendation_status == DynamicPricingRecommendationStatus.OPEN, DynamicPricingRecommendation.generated_at >= cutoff).order_by(DynamicPricingRecommendation.generated_at.desc()).limit(1)).scalar_one_or_none()


def generate_candidates(*, current_price: Decimal, minimum_safe_price: Decimal, competitor_values: list[Decimal | None], increment: Decimal, max_change_rate: Decimal) -> list[Decimal]:
    values = {current_price, minimum_safe_price}
    for rate in [Decimal("-0.10"), Decimal("-0.05"), Decimal("0.05"), Decimal("0.10")]:
        if abs(rate) <= max_change_rate:
            values.add(current_price * (Decimal("1") + rate))
    for value in competitor_values:
        if value is not None:
            values.add(Decimal(str(value)))
    lower = current_price * (Decimal("1") - max_change_rate)
    upper = current_price * (Decimal("1") + max_change_rate)
    rounded = {_round_increment(value, increment) for value in values if lower <= value <= upper and value > 0}
    return sorted(rounded)


def select_candidate(*, evaluations: list[CandidateEvaluation], current_price: Decimal, objective: PricingObjective, min_improvement_rate: Decimal, baseline_profit: Decimal | None, baseline_revenue: Decimal | None) -> CandidateEvaluation | None:
    if not evaluations:
        return None
    current = next((item for item in evaluations if item.candidate_price == current_price), None)
    baseline = baseline_profit if objective == PricingObjective.MAXIMIZE_EXPECTED_PROFIT else baseline_revenue
    ordered = sorted(evaluations, key=lambda item: (item.score, -abs(item.candidate_price - current_price), -item.candidate_price), reverse=True)
    best = ordered[0]
    if baseline is not None and best.score <= baseline * (Decimal("1") + min_improvement_rate):
        return current or best
    return best


def derive_action(*, current_price: Decimal, selected_price: Decimal, min_actionable_change_rate: Decimal) -> DynamicPricingAction:
    if current_price <= 0:
        return DynamicPricingAction.HOLD
    change = (selected_price - current_price) / current_price
    if abs(change) < min_actionable_change_rate:
        return DynamicPricingAction.HOLD
    return DynamicPricingAction.PRICE_LOWER if change < 0 else DynamicPricingAction.PRICE_RAISE


def calculate_penalties(*, candidate_price: Decimal, analytics, estimate: DemandElasticityResult, forecast_confidence: Decimal) -> Decimal:
    penalty = Decimal("0")
    current = Decimal(str(analytics.current_price))
    if forecast_confidence < Decimal("50"):
        penalty += Decimal("50")
    if analytics.data_status == PricingAnalyticsDataStatus.STALE:
        penalty += Decimal("100")
    if current > 0:
        penalty += abs(candidate_price - current) / current * Decimal("50")
    if estimate.sample_count < 6:
        penalty += Decimal("25")
    if analytics.inventory_risk_level in {"HIGH", "CRITICAL"} and candidate_price < current:
        penalty += Decimal("200")
    if analytics.inventory_risk_level == "LOW" and candidate_price < current:
        penalty -= Decimal("20")
    if analytics.competitor_min_price is not None and analytics.competitor_max_price is not None:
        if candidate_price < Decimal(str(analytics.competitor_min_price)) or candidate_price > Decimal(str(analytics.competitor_max_price)):
            penalty += Decimal("40")
    return _money(max(Decimal("0"), penalty))


def _baseline_units(analytics, estimate: DemandElasticityResult) -> Decimal | None:
    if analytics.recent_net_sales is not None:
        return Decimal(str(analytics.recent_net_sales))
    if estimate.baseline_units is not None:
        return estimate.baseline_units
    return None


def _estimate_from_record(record: DemandElasticityEstimate) -> DemandElasticityResult:
    from app.models.demand_elasticity_estimate import DemandEstimateDataStatus
    return DemandElasticityResult(
        method=record.estimation_method,
        elasticity=record.elasticity,
        sample_count=record.sample_count,
        baseline_units=record.baseline_units,
        observation_start=record.observation_start,
        observation_end=record.observation_end,
        price_range=None,
        quality_metrics=record.quality_metrics,
        confidence=record.confidence,
        data_status=record.data_status or DemandEstimateDataStatus.INSUFFICIENT,
        calculation_version=record.calculation_version,
        evidence=record.quality_metrics,
    )


def _round_increment(value: Decimal, increment: Decimal) -> Decimal:
    units = (value / increment).to_integral_value(rounding=ROUND_HALF_UP)
    return _money(units * increment)


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def _score(value: Decimal) -> Decimal:
    return max(Decimal("0"), min(Decimal("100"), value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
