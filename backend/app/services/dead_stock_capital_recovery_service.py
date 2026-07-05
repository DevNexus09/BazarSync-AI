from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dead_stock_assessment import DeadStockAssessment
from app.models.dead_stock_capital_recovery import (
    CapitalRecoveryEstimationMethod,
    CapitalRecoveryEstimateStatus,
    DeadStockCapitalRecoveryEstimate,
)
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction, DeadStockRecoveryRecommendation
from app.models.demand_elasticity_estimate import DemandElasticityEstimate, DemandEstimationMethod
from app.models.product import Product
from app.repositories.dead_stock_capital_recovery_repository import DeadStockCapitalRecoveryRepository
from app.services.demand_response_service import DemandElasticityResult, DemandResponseService
from app.services.margin_guard import MarginGuard

MONEY = Decimal("0.01")
QTY = Decimal("0.0001")
RATIO = Decimal("0.000001")


class CapitalRecoveryRepositoryProtocol(Protocol):
    def product(self, *, seller_id: UUID, product_id: UUID) -> Product | None: ...
    def latest_assessment(self, *, seller_id: UUID, product_id: UUID) -> DeadStockAssessment | None: ...
    def latest_recovery_recommendation(self, *, seller_id: UUID, product_id: UUID) -> DeadStockRecoveryRecommendation | None: ...
    def latest_demand_estimate(self, *, seller_id: UUID, product_id: UUID) -> DemandElasticityEstimate | None: ...
    def promotion_history_for_product(self, *, seller_id: UUID, product_id: UUID) -> list[dict]: ...
    def category_promotion_history(self, *, seller_id: UUID, category: str | None) -> list[dict]: ...
    def add(self, estimate: DeadStockCapitalRecoveryEstimate) -> DeadStockCapitalRecoveryEstimate: ...
    def latest_estimate(self, *, seller_id: UUID, product_id: UUID) -> DeadStockCapitalRecoveryEstimate | None: ...


@dataclass(frozen=True)
class RecoverySimulationInput:
    action: DeadStockRecoveryAction
    candidate_discount: Decimal | None = None
    candidate_price: Decimal | None = None
    duration_days: int | None = None
    eligible_quantity: int | None = None


@dataclass(frozen=True)
class UnitEstimate:
    method: CapitalRecoveryEstimationMethod
    status: CapitalRecoveryEstimateStatus
    confidence: Decimal
    assumptions: dict
    low: Decimal | None
    central: Decimal | None
    high: Decimal | None


class DeadStockCapitalRecoveryService:
    def __init__(
        self,
        db: Session | None = None,
        *,
        repository: CapitalRecoveryRepositoryProtocol | None = None,
        margin_guard_factory=None,
        calculation_version: str | None = None,
    ) -> None:
        if repository is None and db is None:
            raise ValueError("Either db or repository is required.")
        self._db = db
        self._repository = repository or DeadStockCapitalRecoveryRepository(db)  # type: ignore[arg-type]
        self._margin_guard_factory = margin_guard_factory or (lambda session: MarginGuard(session))
        self._calculation_version = calculation_version or settings.dead_stock_capital_recovery_formula_version

    def estimate_for_product(self, *, seller_id: UUID, product_id: UUID, calculated_at: datetime | None = None):
        timestamp = _utc(calculated_at or datetime.now(timezone.utc))
        estimate = self.build_for_product(seller_id=seller_id, product_id=product_id, calculated_at=timestamp, simulation=None)
        return self._repository.add(estimate)

    def simulate_for_product(self, *, seller_id: UUID, product_id: UUID, simulation: RecoverySimulationInput, calculated_at: datetime | None = None):
        return self.build_for_product(
            seller_id=seller_id,
            product_id=product_id,
            calculated_at=_utc(calculated_at or datetime.now(timezone.utc)),
            simulation=simulation,
        )

    def latest_estimate(self, *, seller_id: UUID, product_id: UUID):
        return self._repository.latest_estimate(seller_id=seller_id, product_id=product_id)

    def latest_recovery_recommendation(self, *, seller_id: UUID, product_id: UUID):
        return self._repository.latest_recovery_recommendation(seller_id=seller_id, product_id=product_id)

    def build_for_product(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        calculated_at: datetime,
        simulation: RecoverySimulationInput | None,
    ) -> DeadStockCapitalRecoveryEstimate:
        product = self._repository.product(seller_id=seller_id, product_id=product_id)
        if product is None:
            raise ValueError("Product not found.")
        assessment = self._repository.latest_assessment(seller_id=seller_id, product_id=product_id)
        recommendation = self._repository.latest_recovery_recommendation(seller_id=seller_id, product_id=product_id)
        action = simulation.action if simulation else getattr(recommendation, "primary_action", DeadStockRecoveryAction.HOLD)
        eligible_quantity = _eligible_quantity(product=product, assessment=assessment, recommendation=recommendation, simulation=simulation)
        unit_cost = _decimal_or_none(getattr(product, "cost_price", None))
        locked_capital = _money(Decimal(eligible_quantity) * unit_cost) if unit_cost is not None else None
        candidate_price = _candidate_price(product=product, recommendation=recommendation, simulation=simulation)
        duration = (simulation.duration_days if simulation else getattr(recommendation, "suggested_duration_days", None)) or settings.dead_stock_capital_recovery_default_duration_days

        base_evidence = {
            "currency": settings.dead_stock_capital_recovery_currency,
            "recommended_action": action.value,
            "business_definition": {
                "locked_capital": "eligible_dead_stock_quantity multiplied by authoritative unit landed cost.",
                "cost_basis_recovered": "cash-flow view: the portion of locked capital covered by net cash after marketplace and variable selling costs, capped at locked capital.",
            },
            "simulation": simulation is not None,
            "dead_stock_assessment_id": str(getattr(assessment, "id", "")) if assessment else None,
            "recovery_recommendation_id": str(getattr(recommendation, "id", "")) if recommendation else None,
        }
        if unit_cost is None:
            return self._blocked_estimate(
                product=product,
                assessment=assessment,
                recommendation=recommendation,
                eligible_quantity=eligible_quantity,
                candidate_price=candidate_price,
                status=CapitalRecoveryEstimateStatus.INSUFFICIENT_DATA,
                method=CapitalRecoveryEstimationMethod.INSUFFICIENT_DATA,
                confidence=Decimal("0.00"),
                evidence={**base_evidence, "reason": "MISSING_COST_DATA"},
                calculated_at=calculated_at,
            )
        if eligible_quantity <= 0:
            return self._blocked_estimate(
                product=product,
                assessment=assessment,
                recommendation=recommendation,
                eligible_quantity=0,
                unit_cost=unit_cost,
                locked_capital=Decimal("0.00"),
                candidate_price=candidate_price,
                status=CapitalRecoveryEstimateStatus.INSUFFICIENT_DATA,
                method=CapitalRecoveryEstimationMethod.INSUFFICIENT_DATA,
                confidence=Decimal("0.00"),
                evidence={**base_evidence, "reason": "ZERO_ELIGIBLE_INVENTORY"},
                calculated_at=calculated_at,
            )
        if candidate_price is None or candidate_price <= 0:
            return self._blocked_estimate(
                product=product,
                assessment=assessment,
                recommendation=recommendation,
                eligible_quantity=eligible_quantity,
                unit_cost=unit_cost,
                locked_capital=locked_capital,
                candidate_price=candidate_price,
                status=CapitalRecoveryEstimateStatus.INSUFFICIENT_DATA,
                method=CapitalRecoveryEstimationMethod.INSUFFICIENT_DATA,
                confidence=Decimal("0.00"),
                evidence={**base_evidence, "reason": "MISSING_CANDIDATE_PRICE"},
                calculated_at=calculated_at,
            )

        guard = self._margin_guard_factory(self._db).validate_candidate(
            seller_id=seller_id,
            product=product,
            candidate_price=candidate_price,
        )
        guard_evidence = guard.to_evidence()
        guard_reasons = set(guard_evidence.get("rejection_reasons") or [])
        if not guard.is_allowed and "MISSING_FEE_DATA" in guard_reasons:
            return self._blocked_estimate(
                product=product,
                assessment=assessment,
                recommendation=recommendation,
                eligible_quantity=eligible_quantity,
                unit_cost=unit_cost,
                locked_capital=locked_capital,
                candidate_price=candidate_price,
                status=CapitalRecoveryEstimateStatus.INSUFFICIENT_DATA,
                method=CapitalRecoveryEstimationMethod.INSUFFICIENT_DATA,
                confidence=Decimal("0.00"),
                evidence={**base_evidence, "reason": "MISSING_FEE_DATA", "margin_guard": guard_evidence},
                calculated_at=calculated_at,
            )
        if not guard.is_allowed and action in {DeadStockRecoveryAction.DISCOUNT, DeadStockRecoveryAction.FLASH_SALE}:
            return self._blocked_estimate(
                product=product,
                assessment=assessment,
                recommendation=recommendation,
                eligible_quantity=eligible_quantity,
                unit_cost=unit_cost,
                locked_capital=locked_capital,
                candidate_price=candidate_price,
                status=CapitalRecoveryEstimateStatus.BLOCKED_BY_MARGIN_POLICY,
                method=CapitalRecoveryEstimationMethod.INSUFFICIENT_DATA,
                confidence=Decimal("0.00"),
                evidence={**base_evidence, "reason": "MARGIN_GUARD_REJECTED", "margin_guard": guard_evidence},
                calculated_at=calculated_at,
            )

        unit_estimate = self._estimate_units(
            seller_id=seller_id,
            product=product,
            eligible_quantity=eligible_quantity,
            candidate_price=candidate_price,
            duration_days=duration,
        )
        return self._calculated_estimate(
            product=product,
            assessment=assessment,
            recommendation=recommendation,
            eligible_quantity=eligible_quantity,
            unit_cost=unit_cost,
            locked_capital=locked_capital,
            candidate_price=candidate_price,
            guard=guard,
            unit_estimate=unit_estimate,
            evidence={**base_evidence, "margin_guard": guard_evidence, "duration_days": duration},
            calculated_at=calculated_at,
        )

    def _estimate_units(self, *, seller_id: UUID, product: Product, eligible_quantity: int, candidate_price: Decimal, duration_days: int) -> UnitEstimate:
        demand = self._repository.latest_demand_estimate(seller_id=seller_id, product_id=product.id)
        if demand and demand.elasticity is not None and demand.baseline_units is not None:
            result = DemandElasticityResult(
                method=demand.estimation_method,
                elasticity=demand.elasticity,
                sample_count=demand.sample_count,
                baseline_units=demand.baseline_units,
                observation_start=demand.observation_start,
                observation_end=demand.observation_end,
                price_range=None,
                quality_metrics=demand.quality_metrics,
                confidence=demand.confidence,
                data_status=demand.data_status,
                calculation_version=demand.calculation_version,
                evidence={"source": "persisted_phase7_demand_response"},
            )
            forecast = DemandResponseService().forecast_candidate_units(
                current_price=Decimal(str(product.selling_price)),
                candidate_price=candidate_price,
                baseline_units=demand.baseline_units,
                forecast_horizon_days=duration_days,
                baseline_period={"source": "demand_elasticity_estimate", "sample_count": demand.sample_count},
                estimate=result,
            )
            return UnitEstimate(
                method=CapitalRecoveryEstimationMethod.HISTORICAL_DEMAND_RESPONSE,
                status=CapitalRecoveryEstimateStatus.CALCULATED,
                confidence=forecast.confidence,
                assumptions=forecast.assumptions,
                low=_cap_units(forecast.lower_estimate, eligible_quantity),
                central=_cap_units(forecast.central_estimate, eligible_quantity),
                high=_cap_units(forecast.upper_estimate, eligible_quantity),
            )
        product_history = self._repository.promotion_history_for_product(seller_id=seller_id, product_id=product.id)
        history_estimate = _history_units(product_history, eligible_quantity, "product_promotion_history")
        if history_estimate:
            return history_estimate
        category_history = self._repository.category_promotion_history(seller_id=seller_id, category=product.category)
        category_estimate = _history_units(category_history, eligible_quantity, "category_promotion_history")
        if category_estimate:
            return category_estimate
        return _heuristic_units(eligible_quantity)

    def _calculated_estimate(self, **kwargs) -> DeadStockCapitalRecoveryEstimate:
        product = kwargs["product"]
        unit_cost = kwargs["unit_cost"]
        locked_capital = kwargs["locked_capital"]
        candidate_price = kwargs["candidate_price"]
        units = kwargs["unit_estimate"]
        guard = kwargs["guard"]
        per_unit_fees = _fee_total(guard.to_evidence())
        low = units.low
        central = units.central
        high = units.high
        gross_low = _money((low or Decimal("0")) * candidate_price) if low is not None else None
        gross = _money((central or Decimal("0")) * candidate_price) if central is not None else None
        gross_high = _money((high or Decimal("0")) * candidate_price) if high is not None else None
        net = _money((central or Decimal("0")) * (candidate_price - per_unit_fees)) if central is not None else None
        contribution = _money(net - ((central or Decimal("0")) * unit_cost)) if net is not None else None
        cost_basis = min(locked_capital, net) if locked_capital is not None and net is not None else None
        remaining = _money(max(Decimal("0"), locked_capital - cost_basis)) if locked_capital is not None and cost_basis is not None else None
        ratio = _ratio(cost_basis / locked_capital) if locked_capital and locked_capital > 0 and cost_basis is not None else None
        return DeadStockCapitalRecoveryEstimate(
            seller_id=product.seller_id,
            product_id=product.id,
            dead_stock_assessment_id=getattr(kwargs["assessment"], "id", None),
            recovery_recommendation_id=getattr(kwargs["recommendation"], "id", None),
            eligible_quantity=kwargs["eligible_quantity"],
            unit_cost=_money(unit_cost),
            locked_capital=locked_capital,
            candidate_price=candidate_price,
            expected_units_low=low,
            expected_units=central,
            expected_units_high=high,
            gross_recovered_cash_low=gross_low,
            gross_recovered_cash=gross,
            gross_recovered_cash_high=gross_high,
            net_cash_recovered=net,
            contribution_recovered=contribution,
            cost_basis_recovered=_money(cost_basis) if cost_basis is not None else None,
            remaining_locked_capital=remaining,
            capital_recovery_ratio=ratio,
            estimation_method=units.method,
            estimate_status=units.status,
            confidence_score=_score(units.confidence),
            evidence={**kwargs["evidence"], "unit_estimate": units.assumptions, "per_unit_selling_costs": str(per_unit_fees)},
            calculation_version=self._calculation_version,
            calculated_at=kwargs["calculated_at"],
        )

    def _blocked_estimate(self, *, product: Product, assessment=None, recommendation=None, eligible_quantity: int, unit_cost=None, locked_capital=None, candidate_price=None, status, method, confidence, evidence, calculated_at):
        return DeadStockCapitalRecoveryEstimate(
            seller_id=product.seller_id,
            product_id=product.id,
            dead_stock_assessment_id=getattr(assessment, "id", None),
            recovery_recommendation_id=getattr(recommendation, "id", None),
            eligible_quantity=eligible_quantity,
            unit_cost=_money(unit_cost) if unit_cost is not None else None,
            locked_capital=locked_capital,
            candidate_price=candidate_price,
            expected_units_low=None,
            expected_units=None,
            expected_units_high=None,
            gross_recovered_cash_low=None,
            gross_recovered_cash=None,
            gross_recovered_cash_high=None,
            net_cash_recovered=None,
            contribution_recovered=None,
            cost_basis_recovered=None,
            remaining_locked_capital=locked_capital,
            capital_recovery_ratio=None,
            estimation_method=method,
            estimate_status=status,
            confidence_score=confidence,
            evidence=evidence,
            calculation_version=self._calculation_version,
            calculated_at=calculated_at,
        )


def _eligible_quantity(*, product, assessment, recommendation, simulation) -> int:
    raw = (
        simulation.eligible_quantity
        if simulation and simulation.eligible_quantity is not None
        else getattr(recommendation, "recommended_quantity", None)
        or getattr(assessment, "eligible_quantity", None)
        or getattr(product, "stock_quantity", 0)
        or 0
    )
    return max(0, min(int(raw), int(getattr(product, "stock_quantity", raw) or 0)))


def _candidate_price(*, product, recommendation, simulation) -> Decimal | None:
    if simulation and simulation.candidate_price is not None:
        return _money(simulation.candidate_price)
    if simulation and simulation.candidate_discount is not None:
        return _money(Decimal(str(product.selling_price)) * (Decimal("1") - simulation.candidate_discount))
    price = getattr(recommendation, "recommended_price", None)
    if price is not None:
        return _money(Decimal(str(price)))
    return _money(Decimal(str(product.selling_price))) if getattr(product, "selling_price", None) is not None else None


def _history_units(history: list[dict], eligible_quantity: int, source: str) -> UnitEstimate | None:
    rates = []
    for row in history:
        if row.get("sell_through_rate") is not None:
            rates.append(Decimal(str(row["sell_through_rate"])))
        elif row.get("units_sold") is not None and row.get("eligible_quantity"):
            rates.append(Decimal(str(row["units_sold"])) / Decimal(str(row["eligible_quantity"])))
    if not rates:
        return None
    central_rate = max(Decimal("0"), min(Decimal("1"), sum(rates) / Decimal(len(rates))))
    low_rate = max(Decimal("0"), central_rate * Decimal("0.70"))
    high_rate = min(Decimal("1"), central_rate * Decimal("1.30"))
    method = CapitalRecoveryEstimationMethod.PRODUCT_PROMOTION_HISTORY if source.startswith("product") else CapitalRecoveryEstimationMethod.CATEGORY_PROMOTION_HISTORY
    confidence = Decimal("62.00") if method == CapitalRecoveryEstimationMethod.PRODUCT_PROMOTION_HISTORY else Decimal("48.00")
    return UnitEstimate(
        method=method,
        status=CapitalRecoveryEstimateStatus.LIMITED_DATA,
        confidence=confidence,
        assumptions={"source": source, "sample_count": len(rates), "historical_sell_through_rate": str(_ratio(central_rate))},
        low=_qty(Decimal(eligible_quantity) * low_rate),
        central=_qty(Decimal(eligible_quantity) * central_rate),
        high=_qty(Decimal(eligible_quantity) * high_rate),
    )


def _heuristic_units(eligible_quantity: int) -> UnitEstimate:
    low = Decimal(str(settings.dead_stock_capital_recovery_heuristic_low_sell_through_rate))
    central = Decimal(str(settings.dead_stock_capital_recovery_heuristic_central_sell_through_rate))
    high = Decimal(str(settings.dead_stock_capital_recovery_heuristic_high_sell_through_rate))
    return UnitEstimate(
        method=CapitalRecoveryEstimationMethod.CONSERVATIVE_HEURISTIC,
        status=CapitalRecoveryEstimateStatus.HEURISTIC,
        confidence=Decimal("35.00"),
        assumptions={
            "not_historically_learned": True,
            "low_sell_through_rate": str(low),
            "central_sell_through_rate": str(central),
            "high_sell_through_rate": str(high),
        },
        low=_qty(Decimal(eligible_quantity) * low),
        central=_qty(Decimal(eligible_quantity) * central),
        high=_qty(Decimal(eligible_quantity) * high),
    )


def _cap_units(value: Decimal | None, eligible_quantity: int) -> Decimal | None:
    if value is None:
        return None
    return _qty(min(Decimal(eligible_quantity), max(Decimal("0"), Decimal(str(value)))))


def _fee_total(evidence: dict) -> Decimal:
    fee = evidence.get("fee_breakdown") or {}
    value = fee.get("total_fee_amount")
    if value is not None:
        return Decimal(str(value))
    return Decimal("0")


def _decimal_or_none(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def _qty(value: Decimal) -> Decimal:
    return Decimal(value).quantize(QTY, rounding=ROUND_HALF_UP)


def _ratio(value: Decimal) -> Decimal:
    return Decimal(value).quantize(RATIO, rounding=ROUND_HALF_UP)


def _score(value: Decimal) -> Decimal:
    return max(Decimal("0"), min(Decimal("100"), value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
