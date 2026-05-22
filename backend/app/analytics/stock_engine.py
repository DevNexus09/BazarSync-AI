"""Stock analytics engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.analytics.metrics import (
    PricingConfig,
    compute_availability_counts,
    compute_competitor_price_stats,
    estimate_daily_sales_velocity,
    estimate_days_of_stock_left,
    score_stock_risk,
    score_urgency,
)


@dataclass(frozen=True)
class StockAnalytics:
    estimated_days_of_stock_left: float
    stock_risk_score: float
    urgency_score: float
    competitor_availability_ratio: float
    out_of_stock_competitor_count: int
    in_stock_competitor_count: int


class StockEngine:
    """Computes stock-specific analytics for recommendations."""

    def __init__(self, config: PricingConfig | None = None) -> None:
        self._config = config or PricingConfig()

    def analyze(self, payload: Mapping[str, Any]) -> StockAnalytics:
        seller_price = _require_float(payload, "seller_price")
        stock_quantity = _require_int(payload, "stock_quantity")
        supplier_lead_time = _require_int(payload, "supplier_lead_time")
        competitors = _require_list(payload, "competitors")

        competitor_prices = [
            _require_float(item, "price")
            for item in competitors
            if isinstance(item, Mapping) and item.get("price") is not None
        ]
        availability = compute_availability_counts(
            item.get("stock_status") if isinstance(item, Mapping) else None
            for item in competitors
        )

        stats = compute_competitor_price_stats(competitor_prices)
        competitor_median = stats["median"]
        daily_velocity = estimate_daily_sales_velocity(
            seller_price,
            competitor_median,
            float(availability["ratio"]),
        )
        days_left = estimate_days_of_stock_left(stock_quantity, daily_velocity)
        stock_risk_score = score_stock_risk(
            days_left, supplier_lead_time, self._config.low_stock_days_threshold
        )
        urgency_score = score_urgency(
            pricing_pressure_score=0.0,
            stock_risk_score=stock_risk_score,
        )

        return StockAnalytics(
            estimated_days_of_stock_left=days_left,
            stock_risk_score=stock_risk_score,
            urgency_score=urgency_score,
            competitor_availability_ratio=float(availability["ratio"]),
            out_of_stock_competitor_count=int(availability["out_of_stock"]),
            in_stock_competitor_count=int(availability["in_stock"]),
        )


def _require_float(payload: Mapping[str, Any], key: str) -> float:
    value = payload.get(key)
    if value is None:
        raise ValueError(f"{key} is required.")
    return float(value)


def _require_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if value is None:
        raise ValueError(f"{key} is required.")
    return int(value)


def _require_list(payload: Mapping[str, Any], key: str) -> Sequence[Mapping[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list.")
    return value
