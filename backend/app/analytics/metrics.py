"""Reusable analytics utilities for pricing intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

# ------------------------------
# Configurable thresholds/constants
# ------------------------------

PRICE_UNDERCUT_THRESHOLD_PERCENT = 5.0
LOW_STOCK_DAYS_THRESHOLD = 5
MIN_COMPETITOR_COUNT = 2
MARKETPLACE_FEE_PERCENT = 5.0
DELIVERY_COST_PERCENT = 2.0
PLATFORM_COMMISSION_PERCENT = 8.0
OUT_OF_STOCK_RAISE_RATIO = 0.6
HEALTHY_STOCK_DAYS_THRESHOLD = 10
PRICING_PRESSURE_REFERENCE_PERCENT = 20.0


@dataclass(frozen=True)
class PricingConfig:
    """Central configuration for analytics calculations."""

    price_undercut_threshold_percent: float = PRICE_UNDERCUT_THRESHOLD_PERCENT
    low_stock_days_threshold: int = LOW_STOCK_DAYS_THRESHOLD
    min_competitor_count: int = MIN_COMPETITOR_COUNT
    marketplace_fee_percent: float = MARKETPLACE_FEE_PERCENT
    delivery_cost_percent: float = DELIVERY_COST_PERCENT
    platform_commission_percent: float = PLATFORM_COMMISSION_PERCENT
    out_of_stock_raise_ratio: float = OUT_OF_STOCK_RAISE_RATIO
    healthy_stock_days_threshold: int = HEALTHY_STOCK_DAYS_THRESHOLD
    pricing_pressure_reference_percent: float = PRICING_PRESSURE_REFERENCE_PERCENT


def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    """Clamp values into a normalized range."""
    return max(min_value, min(max_value, value))


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safely divide two numbers and return a default when invalid."""
    if denominator == 0 or not isfinite(denominator) or not isfinite(numerator):
        return default
    return numerator / denominator


def normalize_stock_status(stock_status: str | None) -> str | None:
    """Normalize stock status labels into in_stock/out_of_stock."""
    if not stock_status:
        return None
    normalized = stock_status.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"in_stock", "available", "instock"}:
        return "in_stock"
    if normalized in {"out_of_stock", "outofstock", "oos", "out"}:
        return "out_of_stock"
    return None


def calculate_margin_after_fees(
    selling_price: float, cost_price: float, config: PricingConfig
) -> float:
    """Calculate net margin amount after fees and commissions."""
    if selling_price <= 0:
        raise ValueError("selling_price must be greater than 0.")
    if cost_price < 0:
        raise ValueError("cost_price cannot be negative.")

    total_fee_percent = (
        config.marketplace_fee_percent
        + config.delivery_cost_percent
        + config.platform_commission_percent
    )
    fee_amount = selling_price * (total_fee_percent / 100.0)
    return selling_price - cost_price - fee_amount


def calculate_margin_percent(
    selling_price: float, cost_price: float, config: PricingConfig
) -> float:
    """Return margin as a percent of selling price."""
    margin_amount = calculate_margin_after_fees(selling_price, cost_price, config)
    return safe_divide(margin_amount, selling_price, default=0.0) * 100.0


def compute_price_gap_percent(
    seller_price: float, competitor_price: float | None
) -> float | None:
    """Calculate percentage gap between seller and competitor price."""
    if competitor_price is None or competitor_price <= 0:
        return None
    return ((seller_price - competitor_price) / competitor_price) * 100.0


def compute_competitor_price_stats(
    prices: Sequence[float],
) -> dict[str, float | None]:
    """Compute competitor price aggregates using pandas/numpy."""
    if not prices:
        return {
            "min": None,
            "max": None,
            "average": None,
            "median": None,
            "std_dev": None,
        }

    series = pd.Series(prices, dtype="float64")
    return {
        "min": float(series.min()),
        "max": float(series.max()),
        "average": float(series.mean()),
        "median": float(series.median()),
        "std_dev": float(np.std(series.to_numpy(), ddof=0)),
    }


def compute_availability_counts(
    statuses: Iterable[str | None],
) -> dict[str, float | int]:
    """Count stock availability and ratio."""
    in_stock_count = 0
    out_of_stock_count = 0
    for status in statuses:
        normalized = normalize_stock_status(status)
        if normalized == "in_stock":
            in_stock_count += 1
        elif normalized == "out_of_stock":
            out_of_stock_count += 1

    total = in_stock_count + out_of_stock_count
    ratio = safe_divide(in_stock_count, total, default=0.0)
    return {
        "in_stock": in_stock_count,
        "out_of_stock": out_of_stock_count,
        "total": total,
        "ratio": ratio,
    }


def estimate_daily_sales_velocity(
    seller_price: float, competitor_median: float | None, availability_ratio: float | None
) -> float:
    """Estimate daily sales velocity using pricing and availability signals."""
    price_gap_percent = compute_price_gap_percent(seller_price, competitor_median) or 0.0

    # Lower price than market increases velocity; higher price reduces it.
    price_factor = clamp(1.0 - (price_gap_percent / 30.0), 0.3, 1.5)

    # When competitors are mostly out of stock, demand shifts to the seller.
    availability_factor = (
        1.0 if availability_ratio is None
        else clamp(1.0 + (1.0 - availability_ratio) * 0.8, 0.6, 1.8)
    )

    base_velocity = 1.0
    return max(0.1, base_velocity * price_factor * availability_factor)


def estimate_days_of_stock_left(stock_quantity: int, daily_sales_velocity: float) -> float:
    """Estimate days of stock left with guardrails for zero/low velocity."""
    if stock_quantity <= 0:
        return 0.0
    safe_velocity = max(daily_sales_velocity, 0.1)
    return stock_quantity / safe_velocity


def score_market_position(price_gap_percent: float | None) -> float:
    """Score how favorable the seller's price is versus the market median."""
    if price_gap_percent is None:
        return 0.5
    # -20% gap => best score, +20% gap => lowest score
    return clamp(1.0 - ((price_gap_percent + 20.0) / 40.0), 0.0, 1.0)


def score_pricing_pressure(
    price_gap_percent: float | None, reference_percent: float
) -> float:
    """Score pricing pressure when seller is priced above the market."""
    if price_gap_percent is None or price_gap_percent <= 0:
        return 0.0
    return clamp(price_gap_percent / reference_percent, 0.0, 1.0)


def score_stock_risk(
    days_left: float, lead_time_days: int, low_stock_days_threshold: int
) -> float:
    """Score stock risk using lead time and low-stock thresholds."""
    if days_left <= 0:
        return 1.0
    if lead_time_days <= 0:
        return 0.0

    lead_time_risk = clamp((lead_time_days - days_left) / lead_time_days, 0.0, 1.0)
    low_stock_risk = clamp(
        (low_stock_days_threshold - days_left) / low_stock_days_threshold, 0.0, 1.0
    )
    return clamp(max(lead_time_risk, low_stock_risk), 0.0, 1.0)


def score_market_competitiveness(
    availability_ratio: float, pricing_pressure_score: float
) -> float:
    """Score overall market competitiveness."""
    return clamp((availability_ratio * 0.6) + (pricing_pressure_score * 0.4), 0.0, 1.0)


def score_urgency(pricing_pressure_score: float, stock_risk_score: float) -> float:
    """Score urgency using pricing pressure and stock risk."""
    return clamp((stock_risk_score * 0.6) + (pricing_pressure_score * 0.4), 0.0, 1.0)
