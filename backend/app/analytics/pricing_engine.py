"""Pricing analytics engine.

Example usage:
    sample_input = {
        "seller_price": 1200,
        "seller_cost": 850,
        "stock_quantity": 15,
        "supplier_lead_time": 7,
        "minimum_margin": 12,
        "competitors": [
            {"price": 1100, "stock_status": "in_stock"},
            {"price": 1180, "stock_status": "out_of_stock"},
        ],
    }

    engine = PricingEngine()
    result = engine.analyze(sample_input)
    print(result)

Sample output (with default config):
    {
        "action": "LOWER",
        "confidence": 0.26,
        "competitor_min_price": 1100.0,
        "competitor_max_price": 1180.0,
        "competitor_average_price": 1140.0,
        "competitor_median_price": 1140.0,
        "competitor_price_std_dev": 40.0,
        "seller_vs_median_gap_percent": 5.26,
        "seller_vs_min_gap_percent": 9.09,
        "estimated_margin_percent": 14.17,
        "estimated_margin_amount": 170.0,
        "out_of_stock_competitor_count": 1,
        "in_stock_competitor_count": 1,
        "competitor_availability_ratio": 0.5,
        "estimated_days_of_stock_left": 12.99,
        "market_position_score": 0.37,
        "urgency_score": 0.11,
        "market_competitiveness_score": 0.41,
        "pricing_pressure_score": 0.26,
        "stock_risk_score": 0.0,
        "recommendation_confidence": 0.26,
        "price_gap_percent": 5.26,
        "reason_codes": ["COMPETITOR_MEDIAN_LOWER", "MARGIN_ABOVE_MINIMUM"],
        "competitor_count": 2,
        "invalid_competitor_count": 0,
    }
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, TypedDict

from app.analytics.metrics import (
    PricingConfig,
    calculate_margin_after_fees,
    calculate_margin_percent,
    clamp,
    compute_availability_counts,
    compute_competitor_price_stats,
    compute_price_gap_percent,
    estimate_daily_sales_velocity,
    estimate_days_of_stock_left,
    score_market_competitiveness,
    score_market_position,
    score_pricing_pressure,
    score_stock_risk,
    score_urgency,
    safe_divide,
)


class AnalyticsOutput(TypedDict):
    action: str
    confidence: float
    competitor_min_price: float | None
    competitor_max_price: float | None
    competitor_average_price: float | None
    competitor_median_price: float | None
    competitor_price_std_dev: float | None
    seller_vs_median_gap_percent: float | None
    seller_vs_min_gap_percent: float | None
    estimated_margin_percent: float
    estimated_margin_amount: float
    out_of_stock_competitor_count: int
    in_stock_competitor_count: int
    competitor_availability_ratio: float
    estimated_days_of_stock_left: float
    market_position_score: float
    urgency_score: float
    market_competitiveness_score: float
    pricing_pressure_score: float
    stock_risk_score: float
    recommendation_confidence: float
    price_gap_percent: float | None
    reason_codes: list[str]
    competitor_count: int
    invalid_competitor_count: int


@dataclass(frozen=True)
class CompetitorInput:
    price: float
    stock_status: str | None = None
    rating: float | None = None
    availability: str | None = None


@dataclass(frozen=True)
class SellerInput:
    seller_price: float
    seller_cost: float
    stock_quantity: int
    supplier_lead_time: int
    minimum_margin: float


class PricingEngine:
    """Orchestrates pricing analytics and deterministic recommendations."""

    def __init__(self, config: PricingConfig | None = None) -> None:
        self._config = config or PricingConfig()

    def analyze(self, payload: Mapping[str, Any], *, freshness_aware: bool = False) -> AnalyticsOutput:
        seller = _parse_seller_input(payload)
        competitors, invalid_competitor_count = _parse_competitors(
            payload.get("competitors")
        )

        competitor_prices = [competitor.price for competitor in competitors]
        competitor_stats = compute_competitor_price_stats(competitor_prices)
        availability = compute_availability_counts(
            competitor.stock_status for competitor in competitors
        )

        competitor_median = competitor_stats["median"]
        price_gap_median = compute_price_gap_percent(
            seller.seller_price, competitor_median
        )
        price_gap_min = compute_price_gap_percent(
            seller.seller_price, competitor_stats["min"]
        )

        margin_amount = calculate_margin_after_fees(
            seller.seller_price, seller.seller_cost, self._config
        )
        margin_percent = calculate_margin_percent(
            seller.seller_price, seller.seller_cost, self._config
        )

        availability_ratio = (
            None if freshness_aware and not availability["total"] else float(availability["ratio"])
        )
        daily_velocity = estimate_daily_sales_velocity(seller.seller_price, competitor_median, availability_ratio)
        days_left = estimate_days_of_stock_left(seller.stock_quantity, daily_velocity)

        market_position_score = score_market_position(price_gap_median)
        pricing_pressure_score = score_pricing_pressure(
            price_gap_median, self._config.pricing_pressure_reference_percent
        )
        stock_risk_score = score_stock_risk(
            days_left, seller.supplier_lead_time, self._config.low_stock_days_threshold
        )
        market_competitiveness_score = score_market_competitiveness(
            float(availability["ratio"]), pricing_pressure_score
        )
        urgency_score = score_urgency(pricing_pressure_score, stock_risk_score)

        action, reason_codes = self._decide_action(
            seller=seller,
            competitor_count=len(competitor_prices),
            competitor_median=competitor_median,
            price_gap_median=price_gap_median,
            margin_percent=margin_percent,
            availability=availability,
            days_left=days_left,
            stock_risk_score=stock_risk_score,
        )

        if invalid_competitor_count > 0:
            reason_codes.append("COMPETITOR_DATA_INCOMPLETE")
        if not competitor_prices:
            reason_codes.append("NO_COMPETITOR_DATA")

        out_of_stock_ratio = safe_divide(
            float(availability["out_of_stock"]),
            float(availability["total"]),
            default=0.0,
        )
        recommendation_confidence = self._compute_confidence(
            action=action,
            pricing_pressure_score=pricing_pressure_score,
            stock_risk_score=stock_risk_score,
            out_of_stock_ratio=out_of_stock_ratio,
            market_position_score=market_position_score,
            competitor_count=len(competitor_prices),
        )

        return {
            "action": action,
            "confidence": round(recommendation_confidence, 2),
            "competitor_min_price": competitor_stats["min"],
            "competitor_max_price": competitor_stats["max"],
            "competitor_average_price": competitor_stats["average"],
            "competitor_median_price": competitor_stats["median"],
            "competitor_price_std_dev": competitor_stats["std_dev"],
            "seller_vs_median_gap_percent": _round_or_none(price_gap_median, 2),
            "seller_vs_min_gap_percent": _round_or_none(price_gap_min, 2),
            "estimated_margin_percent": round(margin_percent, 2),
            "estimated_margin_amount": round(margin_amount, 2),
            "out_of_stock_competitor_count": int(availability["out_of_stock"]),
            "in_stock_competitor_count": int(availability["in_stock"]),
            "competitor_availability_ratio": round(float(availability["ratio"]), 2),
            "estimated_days_of_stock_left": round(days_left, 2),
            "market_position_score": round(market_position_score, 2),
            "urgency_score": round(urgency_score, 2),
            "market_competitiveness_score": round(market_competitiveness_score, 2),
            "pricing_pressure_score": round(pricing_pressure_score, 2),
            "stock_risk_score": round(stock_risk_score, 2),
            "recommendation_confidence": round(recommendation_confidence, 2),
            "price_gap_percent": _round_or_none(price_gap_median, 2),
            "reason_codes": reason_codes,
            "competitor_count": len(competitor_prices),
            "invalid_competitor_count": invalid_competitor_count,
        }

    def _decide_action(
        self,
        *,
        seller: SellerInput,
        competitor_count: int,
        competitor_median: float | None,
        price_gap_median: float | None,
        margin_percent: float,
        availability: Mapping[str, float | int],
        days_left: float,
        stock_risk_score: float,
    ) -> tuple[str, list[str]]:
        reason_codes: list[str] = []

        # RULE 3 — REORDER: stock depletion before lead time.
        if days_left < seller.supplier_lead_time:
            reason_codes.append("STOCK_DEPLETION_RISK")
            return "REORDER", reason_codes

        # RULE 1 — LOWER PRICE: above median with safe margin.
        if (
            competitor_median is not None
            and competitor_count >= self._config.min_competitor_count
            and price_gap_median is not None
            and price_gap_median >= self._config.price_undercut_threshold_percent
            and margin_percent >= seller.minimum_margin
        ):
            reason_codes.extend(["COMPETITOR_MEDIAN_LOWER", "MARGIN_ABOVE_MINIMUM"])
            return "LOWER", reason_codes

        # RULE 2 — RAISE PRICE: many competitors out of stock + healthy stock.
        out_of_stock_ratio = safe_divide(
            float(availability["out_of_stock"]),
            float(availability["total"]),
            default=0.0,
        )
        if (
            availability["total"] >= self._config.min_competitor_count
            and out_of_stock_ratio >= self._config.out_of_stock_raise_ratio
            and days_left >= self._config.healthy_stock_days_threshold
        ):
            reason_codes.extend(["COMPETITOR_STOCKOUT", "HEALTHY_STOCK"])
            return "RAISE", reason_codes

        # RULE 4 — HOLD: healthy pricing position and low stock risk.
        price_healthy = (
            price_gap_median is None
            or abs(price_gap_median) < self._config.price_undercut_threshold_percent
        )
        stock_risk_low = stock_risk_score < 0.3
        if price_healthy and stock_risk_low:
            reason_codes.extend(["PRICE_POSITION_HEALTHY", "LOW_STOCK_RISK"])
        else:
            if price_gap_median is not None:
                reason_codes.append("PRICE_WITHIN_RANGE")
            if stock_risk_score >= 0.3:
                reason_codes.append("ELEVATED_STOCK_RISK")
        return "HOLD", reason_codes

    def _compute_confidence(
        self,
        *,
        action: str,
        pricing_pressure_score: float,
        stock_risk_score: float,
        out_of_stock_ratio: float,
        market_position_score: float,
        competitor_count: int,
    ) -> float:
        """Blend signal strength with data quality to produce confidence."""
        data_quality_factor = clamp(
            safe_divide(
                float(competitor_count),
                float(self._config.min_competitor_count),
                default=0.0,
            ),
            0.0,
            1.0,
        )

        if action == "LOWER":
            base = pricing_pressure_score
        elif action == "RAISE":
            base = out_of_stock_ratio
        elif action == "REORDER":
            base = stock_risk_score
        else:
            base = clamp((market_position_score + (1.0 - stock_risk_score)) / 2.0, 0.0, 1.0)

        return clamp(base * (0.5 + 0.5 * data_quality_factor), 0.0, 1.0)


def _parse_seller_input(payload: Mapping[str, Any]) -> SellerInput:
    """Validate and normalize seller inputs."""
    seller_price = _require_float(payload, "seller_price", positive=True)
    seller_cost = _require_float(payload, "seller_cost", non_negative=True)
    stock_quantity = _require_int(payload, "stock_quantity", non_negative=True)
    supplier_lead_time = _require_int(payload, "supplier_lead_time", non_negative=True)
    minimum_margin = _require_float(payload, "minimum_margin", non_negative=True)

    return SellerInput(
        seller_price=seller_price,
        seller_cost=seller_cost,
        stock_quantity=stock_quantity,
        supplier_lead_time=supplier_lead_time,
        minimum_margin=minimum_margin,
    )


def _parse_competitors(raw_competitors: Any) -> tuple[list[CompetitorInput], int]:
    """Parse competitor payloads while tracking invalid entries."""
    if raw_competitors is None:
        return [], 0
    if not isinstance(raw_competitors, list):
        raise ValueError("competitors must be a list.")

    competitors: list[CompetitorInput] = []
    invalid_count = 0
    for entry in raw_competitors:
        if not isinstance(entry, Mapping):
            invalid_count += 1
            continue

        price = _optional_float(entry.get("price"), positive=True)
        if price is None:
            invalid_count += 1
            continue

        competitors.append(
            CompetitorInput(
                price=price,
                stock_status=_optional_string(entry.get("stock_status")),
                rating=_optional_float(entry.get("rating"), non_negative=True),
                availability=_optional_string(entry.get("availability")),
            )
        )

    return competitors, invalid_count


def _require_float(
    payload: Mapping[str, Any],
    field: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> float:
    value = payload.get(field)
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} is required and must be a number.")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number.") from exc

    if positive and numeric <= 0:
        raise ValueError(f"{field} must be greater than 0.")
    if non_negative and numeric < 0:
        raise ValueError(f"{field} cannot be negative.")

    return numeric


def _require_int(
    payload: Mapping[str, Any], field: str, *, non_negative: bool = False
) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} is required and must be an integer.")
    try:
        numeric = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer.") from exc

    if non_negative and numeric < 0:
        raise ValueError(f"{field} cannot be negative.")

    return numeric


def _optional_float(
    value: Any, *, positive: bool = False, non_negative: bool = False
) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if positive and numeric <= 0:
        return None
    if non_negative and numeric < 0:
        return None
    return numeric


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return None


def _round_or_none(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(value, digits)


if __name__ == "__main__":
    sample_payload = {
        "seller_price": 1200,
        "seller_cost": 850,
        "stock_quantity": 15,
        "supplier_lead_time": 7,
        "minimum_margin": 12,
        "competitors": [
            {"price": 1100, "stock_status": "in_stock"},
            {"price": 1180, "stock_status": "out_of_stock"},
        ],
    }

    engine = PricingEngine()
    print(engine.analyze(sample_payload))
