from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dynamic_pricing_recommendation import DynamicPricingAction
from app.models.product import Product
from app.services.demand_response_service import DemandElasticityResult, DemandResponseService
from app.services.margin_guard import MarginGuard
from app.services.pricing_analytics_service import PricingAnalyticsService
from app.services.pricing_calculator import PricingCalculationError

MONEY = Decimal("0.01")
QUANTITY = Decimal("0.0001")
SCORE = Decimal("0.01")


@dataclass(frozen=True)
class RevenueSimulationScenarioResult:
    candidate_price: Decimal
    action: DynamicPricingAction
    is_allowed: bool
    rejection_reasons: list[str]
    expected_units_lower: Decimal | None
    expected_units: Decimal | None
    expected_units_upper: Decimal | None
    expected_revenue: Decimal | None
    expected_profit: Decimal | None
    revenue_impact: Decimal | None
    profit_impact: Decimal | None
    unit_profit: Decimal | None
    margin_rate: Decimal | None
    minimum_safe_price: Decimal | None
    confidence_score: Decimal
    estimation_method: object
    data_status: object
    evidence: dict[str, object]


@dataclass(frozen=True)
class RevenueSimulationResult:
    seller_id: UUID
    product_id: UUID
    product_title: str
    pricing_analytics_id: UUID
    current_price: Decimal
    baseline_units: Decimal | None
    baseline_expected_revenue: Decimal | None
    baseline_expected_profit: Decimal | None
    forecast_horizon_days: int
    demand_method: object
    data_status: object
    confidence_score: Decimal
    calculated_at: datetime
    scenarios: list[RevenueSimulationScenarioResult]
    evidence: dict[str, object]


class RevenueSimulatorService:
    """Deterministic revenue simulation using Phase 7 guardrails and forecasts."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def simulate(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        candidate_prices: list[Decimal],
        forecast_horizon_days: int,
    ) -> RevenueSimulationResult:
        product = self._product(seller_id=seller_id, product_id=product_id)
        analytics_service = PricingAnalyticsService(self._db)
        analytics = analytics_service.latest(seller_id=seller_id, product_id=product_id)
        if analytics is None:
            try:
                analytics = analytics_service.generate_for_product(
                    seller_id=seller_id,
                    product_id=product_id,
                )
            except (PricingCalculationError, ValueError) as exc:
                raise ValueError(
                    "Pricing analytics could not be prepared. Check the product cost and pricing policy setup."
                ) from exc

        estimate = DemandResponseService(self._db).estimate_for_product(
            seller_id=seller_id,
            product_id=product_id,
            as_of_date=datetime.now(timezone.utc).date(),
        )
        baseline_units = _baseline_units(analytics, estimate, forecast_horizon_days)
        baseline_guard = MarginGuard(self._db).validate_candidate(
            seller_id=seller_id,
            product=product,
            candidate_price=Decimal(str(analytics.current_price)),
        )
        baseline_revenue = (
            _money(Decimal(str(analytics.current_price)) * baseline_units)
            if baseline_units is not None
            else None
        )
        baseline_profit = (
            _money((baseline_guard.unit_profit or Decimal("0")) * baseline_units)
            if baseline_units is not None and baseline_guard.unit_profit is not None
            else None
        )
        deduped_candidates = _dedupe_prices(candidate_prices)
        scenarios = [
            self._scenario(
                seller_id=seller_id,
                product=product,
                analytics=analytics,
                estimate=estimate,
                candidate_price=price,
                baseline_units=baseline_units,
                baseline_revenue=baseline_revenue,
                baseline_profit=baseline_profit,
                forecast_horizon_days=forecast_horizon_days,
            )
            for price in deduped_candidates
        ]
        confidence = _score(
            (Decimal(str(analytics.confidence_score)) + Decimal(str(estimate.confidence)))
            / Decimal("2")
        )
        return RevenueSimulationResult(
            seller_id=seller_id,
            product_id=product_id,
            product_title=product.title,
            pricing_analytics_id=analytics.id,
            current_price=_money(Decimal(str(analytics.current_price))),
            baseline_units=baseline_units,
            baseline_expected_revenue=baseline_revenue,
            baseline_expected_profit=baseline_profit,
            forecast_horizon_days=forecast_horizon_days,
            demand_method=estimate.method,
            data_status=estimate.data_status,
            confidence_score=confidence,
            calculated_at=datetime.now(timezone.utc),
            scenarios=scenarios,
            evidence={
                "pricing_analytics_status": analytics.data_status.value,
                "demand_quality": estimate.quality_metrics,
                "demand_evidence": estimate.evidence,
                "baseline_source": _baseline_source(analytics, estimate),
                "simulation_note": "Simulation does not apply prices. Margin guard rejection blocks revenue and profit projections.",
            },
        )

    def _scenario(
        self,
        *,
        seller_id: UUID,
        product: Product,
        analytics,
        estimate: DemandElasticityResult,
        candidate_price: Decimal,
        baseline_units: Decimal | None,
        baseline_revenue: Decimal | None,
        baseline_profit: Decimal | None,
        forecast_horizon_days: int,
    ) -> RevenueSimulationScenarioResult:
        candidate = _money(candidate_price)
        guard = MarginGuard(self._db).validate_candidate(
            seller_id=seller_id,
            product=product,
            candidate_price=candidate,
        )
        forecast = DemandResponseService().forecast_candidate_units(
            current_price=Decimal(str(analytics.current_price)),
            candidate_price=candidate,
            baseline_units=baseline_units or Decimal("0"),
            forecast_horizon_days=forecast_horizon_days,
            baseline_period={
                "source": _baseline_source(analytics, estimate),
                "baseline_units": str(baseline_units) if baseline_units is not None else None,
            },
            estimate=estimate,
        )
        expected_units = forecast.central_estimate if guard.is_allowed and baseline_units is not None else None
        expected_revenue = _money(candidate * expected_units) if expected_units is not None else None
        expected_profit = (
            _money((guard.unit_profit or Decimal("0")) * expected_units)
            if expected_units is not None and guard.unit_profit is not None
            else None
        )
        return RevenueSimulationScenarioResult(
            candidate_price=candidate,
            action=_derive_action(
                current_price=Decimal(str(analytics.current_price)),
                candidate_price=candidate,
            ),
            is_allowed=guard.is_allowed,
            rejection_reasons=[reason.value for reason in guard.rejection_reasons],
            expected_units_lower=forecast.lower_estimate if guard.is_allowed else None,
            expected_units=expected_units,
            expected_units_upper=forecast.upper_estimate if guard.is_allowed else None,
            expected_revenue=expected_revenue,
            expected_profit=expected_profit,
            revenue_impact=_money(expected_revenue - baseline_revenue)
            if expected_revenue is not None and baseline_revenue is not None
            else None,
            profit_impact=_money(expected_profit - baseline_profit)
            if expected_profit is not None and baseline_profit is not None
            else None,
            unit_profit=guard.unit_profit,
            margin_rate=guard.margin_rate,
            minimum_safe_price=guard.minimum_safe_price,
            confidence_score=_score(forecast.confidence),
            estimation_method=forecast.method,
            data_status=forecast.data_status,
            evidence={
                "margin_guard": guard.to_evidence(),
                "forecast_assumptions": forecast.assumptions,
                "forecast_formula_version": forecast.calculation_version,
            },
        )

    def _product(self, *, seller_id: UUID, product_id: UUID) -> Product:
        product = self._db.execute(
            select(Product).where(Product.seller_id == seller_id, Product.id == product_id)
        ).scalar_one_or_none()
        if product is None:
            raise ValueError("Product not found.")
        return product


def _baseline_units(analytics, estimate: DemandElasticityResult, horizon_days: int) -> Decimal | None:
    if analytics.recent_net_sales is not None:
        return _quantity(Decimal(str(analytics.recent_net_sales)))
    if analytics.daily_sales_rate is not None:
        return _quantity(Decimal(str(analytics.daily_sales_rate)) * Decimal(horizon_days))
    if estimate.baseline_units is not None:
        return _quantity(Decimal(str(estimate.baseline_units)) * Decimal(horizon_days))
    return None


def _baseline_source(analytics, estimate: DemandElasticityResult) -> str:
    if analytics.recent_net_sales is not None:
        return "pricing_analytics_recent_net_sales"
    if analytics.daily_sales_rate is not None:
        return "pricing_analytics_daily_sales_rate"
    if estimate.baseline_units is not None:
        return "demand_response_baseline_units"
    return "missing"


def _derive_action(*, current_price: Decimal, candidate_price: Decimal) -> DynamicPricingAction:
    current = Decimal(str(current_price))
    candidate = Decimal(str(candidate_price))
    if current <= 0 or candidate == current:
        return DynamicPricingAction.HOLD
    return DynamicPricingAction.PRICE_LOWER if candidate < current else DynamicPricingAction.PRICE_RAISE


def _dedupe_prices(candidate_prices: list[Decimal]) -> list[Decimal]:
    values = {_money(Decimal(str(price))) for price in candidate_prices if Decimal(str(price)) > 0}
    if not values:
        raise ValueError("At least one positive candidate price is required.")
    return sorted(values)


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def _quantity(value: Decimal) -> Decimal:
    return Decimal(value).quantize(QUANTITY, rounding=ROUND_HALF_UP)


def _score(value: Decimal) -> Decimal:
    return max(Decimal("0"), min(Decimal("100"), Decimal(value))).quantize(SCORE, rounding=ROUND_HALF_UP)
