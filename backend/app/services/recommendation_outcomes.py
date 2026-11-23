"""Outcome rules for acted-on recommendations (Phase 6). Pure functions, Decimal for money."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

OUTCOME_VERSION = "outcome-v1"
# The observed price after "applied" must be within this share of the suggested price to attribute the result.
PRICE_APPLIED_TOLERANCE = Decimal("0.02")
PRICING_HORIZON_DAYS = 30
CONFIDENCE_BANDS = (("LOW", Decimal("0"), Decimal("40")), ("MEDIUM", Decimal("40"), Decimal("70")), ("HIGH", Decimal("70"), Decimal("100.01")))


@dataclass(frozen=True)
class OutcomeResult:
    observed: bool
    predicted_value: Decimal | None
    observed_value: Decimal | None
    hit: bool | None
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SaleLine:
    day: date
    unit_price: Decimal | None
    net_units: int


def reorder_window_days(base_window: int, lead_time_days: int, safety_buffer_days: int) -> int:
    """Long enough for the ordered stock to arrive: at least the base window, or lead time plus buffer."""
    return max(base_window, lead_time_days + safety_buffer_days)


def evaluate_reorder(
    *,
    decided_on: date,
    window_days: int,
    daily_sales_rate: Decimal,
    reorder_deadline: date | None,
    units_by_day: dict[date, int],
    available_by_day: dict[date, int],
) -> OutcomeResult:
    """Hit = no stockout in the window after the seller marked the reorder as ordered."""
    days = [decided_on + timedelta(days=offset) for offset in range(window_days)]
    observed_units = Decimal(sum(units_by_day.get(day, 0) for day in days))
    predicted_units = _q4(daily_sales_rate * window_days)
    snapshots = [day for day in days if day in available_by_day]
    stockouts = [day for day in snapshots if available_by_day[day] <= 0]
    details: dict[str, object] = {
        "window_end": (decided_on + timedelta(days=window_days - 1)).isoformat(),
        "reorder_deadline": reorder_deadline.isoformat() if reorder_deadline else None,
        "stock_snapshots_in_window": len(snapshots),
        "stockout_days": len(stockouts),
        "first_stockout": stockouts[0].isoformat() if stockouts else None,
        "stockout_before_deadline": bool(reorder_deadline and stockouts and stockouts[0] <= reorder_deadline),
        "units_error_rate": str(_q4((observed_units - predicted_units) / predicted_units)) if predicted_units > 0 else None,
        "note": "Sold units can be lower than demand on stocked-out days.",
    }
    if not snapshots:
        # Missing stock counts are unknown, not "never ran out".
        return OutcomeResult(False, predicted_units, observed_units, None, {**details, "unavailable_reason": "no_stock_snapshots_in_window"})
    return OutcomeResult(True, predicted_units, observed_units, not stockouts, details)


def evaluate_price_change(
    *,
    before: list[SaleLine],
    after: list[SaleLine],
    recommended_price: Decimal,
    current_price: Decimal,
    unit_cost: Decimal,
    percentage_fee_rate: Decimal,
    fixed_fee_amount: Decimal,
    predicted_profit_impact: Decimal | None,
    window_days: int,
) -> OutcomeResult:
    """Profit in the window after the price was applied versus the same-length window before it."""
    predicted = (
        _money(predicted_profit_impact * Decimal(window_days) / Decimal(PRICING_HORIZON_DAYS))
        if predicted_profit_impact is not None
        else None
    )
    priced_after = [line for line in after if line.unit_price is not None and line.net_units > 0]
    priced_before = [line for line in before if line.unit_price is not None and line.net_units > 0]
    details: dict[str, object] = {
        "units_before": sum(line.net_units for line in before),
        "units_after": sum(line.net_units for line in after),
        "recommended_price": str(recommended_price),
        "price_before_recommendation": str(current_price),
        "cost_basis": "current product cost price",
        "fee_basis": "analytics snapshot fee rate; fixed fees per unit, as in MarginGuard",
        "applied_tolerance": str(PRICE_APPLIED_TOLERANCE),
    }
    if not priced_before or not priced_after:
        return OutcomeResult(False, predicted, None, None, {**details, "unavailable_reason": "no_priced_sales_before_or_after"})
    average_after = _average_price(priced_after)
    details["average_price_after"] = str(average_after)
    if abs(average_after - recommended_price) > recommended_price * PRICE_APPLIED_TOLERANCE:
        # The seller marked it applied but sold at a different price, so the result can't be attributed.
        return OutcomeResult(False, predicted, None, None, {**details, "unavailable_reason": "price_not_applied"})
    profit_before = _profit(priced_before, unit_cost, percentage_fee_rate, fixed_fee_amount)
    profit_after = _profit(priced_after, unit_cost, percentage_fee_rate, fixed_fee_amount)
    observed = profit_after - profit_before
    details.update({"profit_before": str(profit_before), "profit_after": str(profit_after)})
    hit = None if predicted is None else (observed >= 0) == (predicted >= 0)
    return OutcomeResult(True, predicted, observed, hit, details)


def confidence_band(score: Decimal | None) -> str | None:
    if score is None:
        return None
    for name, low, high in CONFIDENCE_BANDS:
        if low <= score < high:
            return name
    return None


def track_record(rows: list[tuple[bool | None, Decimal | None]], *, min_outcomes: int) -> dict[str, object]:
    """Hit rates overall and per confidence band, from (hit, confidence) of observed outcomes."""
    judged = [(hit, score) for hit, score in rows if hit is not None]

    def summary(items: Sequence[tuple[bool | None, Decimal | None]]) -> dict[str, object]:
        hits = sum(1 for hit, _ in items if hit)
        return {
            "outcomes": len(items),
            "hit_rate": round(hits / len(items), 4) if items else None,
            "reliable": len(items) >= min_outcomes,
        }

    return {
        **summary(judged),
        "min_outcomes": min_outcomes,
        "bands": {name: summary([row for row in judged if confidence_band(row[1]) == name]) for name, _, _ in CONFIDENCE_BANDS},
    }


def _profit(lines: list[SaleLine], unit_cost: Decimal, fee_rate: Decimal, fixed_fee: Decimal) -> Decimal:
    total = Decimal("0")
    for line in lines:
        assert line.unit_price is not None
        unit_profit = line.unit_price - line.unit_price * fee_rate - fixed_fee - unit_cost
        total += unit_profit * line.net_units
    return _money(total)


def _average_price(lines: list[SaleLine]) -> Decimal:
    units = sum(line.net_units for line in lines)
    return _money(sum((line.unit_price or Decimal("0")) * line.net_units for line in lines) / Decimal(units))


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q4(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
