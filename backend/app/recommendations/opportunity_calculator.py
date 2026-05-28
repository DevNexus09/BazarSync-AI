"""Deterministic revenue opportunity calculator."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import logging
from typing import Any, Mapping

from app.analytics.metrics import clamp, safe_divide
from app.recommendations.urgency_rules import OpportunityConfig


class OpportunityCalculationError(Exception):
    """Raised when opportunity calculations fail."""


@dataclass(frozen=True)
class OpportunityInput:
    seller_price: float
    recommended_price: float | None
    current_stock: int
    margin_percent: float
    opportunity_score: float
    demand_indicator: float
    competitor_oos_ratio: float
    inventory_turnover_days: float | None = None
    historical_daily_sales: float | None = None


@dataclass(frozen=True)
class OpportunityResult:
    additional_revenue: float
    inventory_capture_units: float
    projected_demand_shift: float
    estimated_profit_impact: float
    revenue_opportunity_score: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "additional_revenue": round(self.additional_revenue, 2),
            "inventory_capture_units": round(self.inventory_capture_units, 2),
            "projected_demand_shift": round(self.projected_demand_shift, 2),
            "estimated_profit_impact": round(self.estimated_profit_impact, 2),
            "revenue_opportunity_score": self.revenue_opportunity_score,
        }


class OpportunityCalculator:
    """Calculates deterministic opportunity and profit impact estimates."""

    def __init__(
        self,
        *,
        config: OpportunityConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config or OpportunityConfig()
        self._logger = logger or logging.getLogger(__name__)

    def calculate(self, input_data: OpportunityInput) -> OpportunityResult:
        self._validate_input(input_data)
        base_daily_demand = self._estimate_base_demand(input_data)
        demand_shift_multiplier = self._compute_demand_shift(input_data)

        projected_demand_shift = (
            base_daily_demand * demand_shift_multiplier * self._config.demand_window_days
        )
        capture_units = min(
            float(input_data.current_stock),
            projected_demand_shift * self._config.capture_rate,
        )
        target_price = input_data.recommended_price or input_data.seller_price
        additional_revenue = capture_units * target_price
        profit_impact = additional_revenue * (input_data.margin_percent / 100.0)
        opportunity_score = self._compute_opportunity_score(input_data)

        self._logger.info(
            "opportunity_calculated revenue=%s capture_units=%s",
            round(additional_revenue, 2),
            round(capture_units, 2),
        )

        return OpportunityResult(
            additional_revenue=additional_revenue,
            inventory_capture_units=capture_units,
            projected_demand_shift=projected_demand_shift,
            estimated_profit_impact=profit_impact,
            revenue_opportunity_score=opportunity_score,
        )

    def calculate_from_payload(self, payload: Mapping[str, Any]) -> OpportunityResult:
        input_data = self._parse_payload(payload)
        return self.calculate(input_data)

    def _validate_input(self, input_data: OpportunityInput) -> None:
        if input_data.seller_price <= 0:
            raise OpportunityCalculationError("seller_price must be positive.")
        if input_data.current_stock < 0:
            raise OpportunityCalculationError("current_stock cannot be negative.")
        if not isfinite(input_data.margin_percent):
            raise OpportunityCalculationError("margin_percent must be finite.")

    def _estimate_base_demand(self, input_data: OpportunityInput) -> float:
        if input_data.historical_daily_sales and input_data.historical_daily_sales > 0:
            return input_data.historical_daily_sales
        if input_data.inventory_turnover_days and input_data.inventory_turnover_days > 0:
            return safe_divide(
                float(input_data.current_stock),
                input_data.inventory_turnover_days,
                default=self._config.base_daily_demand,
            )
        return self._config.base_daily_demand

    def _compute_demand_shift(self, input_data: OpportunityInput) -> float:
        raw_boost = (
            input_data.opportunity_score * self._config.opportunity_multiplier
            + input_data.demand_indicator * self._config.demand_multiplier
            + input_data.competitor_oos_ratio * self._config.out_of_stock_multiplier
        )
        boost = clamp(raw_boost, 0.0, self._config.max_demand_boost)
        return 1.0 + boost

    def _compute_opportunity_score(self, input_data: OpportunityInput) -> int:
        score = clamp(
            (input_data.opportunity_score * 0.4)
            + (input_data.demand_indicator * 0.3)
            + (input_data.competitor_oos_ratio * 0.3),
            0.0,
            1.0,
        )
        return int(round(score * 100))

    def _parse_payload(self, payload: Mapping[str, Any]) -> OpportunityInput:
        if not isinstance(payload, Mapping):
            raise OpportunityCalculationError("Payload must be a mapping.")

        def require_float(key: str) -> float:
            value = payload.get(key)
            if value is None or isinstance(value, bool):
                raise OpportunityCalculationError(f"{key} is required.")
            try:
                return float(value)
            except (TypeError, ValueError) as exc:
                raise OpportunityCalculationError(f"{key} must be numeric.") from exc

        seller_price = require_float("seller_price")
        recommended_price = _optional_float(payload.get("recommended_price"), positive=True)
        try:
            current_stock = int(payload.get("current_stock") or 0)
        except (TypeError, ValueError) as exc:
            raise OpportunityCalculationError("current_stock must be an integer.") from exc
        margin_percent = require_float("margin_percent")
        opportunity_score = _optional_float(
            payload.get("opportunity_score"), min_value=0.0, max_value=1.0
        ) or 0.0
        demand_indicator = _optional_float(
            payload.get("demand_indicator"), min_value=0.0, max_value=1.0
        ) or 0.0
        competitor_oos_ratio = _optional_float(
            payload.get("competitor_oos_ratio"), min_value=0.0, max_value=1.0
        ) or 0.0
        inventory_turnover_days = _optional_float(
            payload.get("inventory_turnover_days"), non_negative=True
        )
        historical_daily_sales = _optional_float(
            payload.get("historical_daily_sales"), non_negative=True
        )

        return OpportunityInput(
            seller_price=seller_price,
            recommended_price=recommended_price,
            current_stock=current_stock,
            margin_percent=margin_percent,
            opportunity_score=opportunity_score,
            demand_indicator=demand_indicator,
            competitor_oos_ratio=competitor_oos_ratio,
            inventory_turnover_days=inventory_turnover_days,
            historical_daily_sales=historical_daily_sales,
        )


def _optional_float(
    value: Any,
    *,
    positive: bool = False,
    non_negative: bool = False,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(numeric):
        return None
    if positive and numeric <= 0:
        return None
    if non_negative and numeric < 0:
        return None
    if min_value is not None and numeric < min_value:
        return None
    if max_value is not None and numeric > max_value:
        return None
    return numeric


EXAMPLE_INPUT: dict[str, Any] = {
    "seller_price": 450,
    "recommended_price": 465,
    "current_stock": 20,
    "margin_percent": 18.0,
    "opportunity_score": 0.75,
    "demand_indicator": 0.65,
    "competitor_oos_ratio": 0.5,
    "inventory_turnover_days": 10,
}

EXAMPLE_EXPECTED_OUTPUT: dict[str, Any] = {
    "revenue_opportunity_score": 71,
}


if __name__ == "__main__":
    sample = OpportunityInput(
        seller_price=450,
        recommended_price=465,
        current_stock=20,
        margin_percent=18.0,
        opportunity_score=0.75,
        demand_indicator=0.65,
        competitor_oos_ratio=0.5,
        inventory_turnover_days=10,
    )
    calculator = OpportunityCalculator()
    print(calculator.calculate(sample).to_dict())
