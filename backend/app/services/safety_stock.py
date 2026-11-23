"""Variability-based safety stock (Phase 5.2): z(service level) × σ_daily × √lead time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from statistics import NormalDist, stdev


@dataclass(frozen=True)
class SafetyStock:
    status: str  # "ok" or why it could not be used
    units: int | None = None
    service_level: Decimal | None = None
    daily_std_dev: Decimal | None = None
    z_score: Decimal | None = None
    days_used: int = 0
    days_censored: int = 0

    def evidence(self) -> dict[str, object]:
        return {
            "safety_stock_status": self.status,
            "safety_stock_units": self.units,
            "safety_stock_service_level": str(self.service_level) if self.service_level is not None else None,
            "demand_daily_std_dev": str(self.daily_std_dev) if self.daily_std_dev is not None else None,
            "safety_stock_z_score": str(self.z_score) if self.z_score is not None else None,
            "demand_history_days_used": self.days_used,
            "demand_history_days_censored": self.days_censored,
        }


def variability_safety_stock(
    *,
    units_by_day: dict[date, int],
    available_by_day: dict[date, int],
    start: date,
    end: date,
    lead_time_days: int,
    service_level: Decimal,
    min_days: int,
) -> SafetyStock:
    """Days with no sales count as zero demand; days that ended with no stock are left out (lost sales)."""
    values: list[int] = []
    censored = 0
    day = start
    while day <= end:
        available = available_by_day.get(day)
        if available is not None and available <= 0:
            censored += 1
        else:
            values.append(units_by_day.get(day, 0))
        day += timedelta(days=1)
    if lead_time_days <= 0:
        return SafetyStock("missing_lead_time", days_used=len(values), days_censored=censored)
    if len(values) < min_days:
        return SafetyStock("insufficient_history", days_used=len(values), days_censored=censored)
    sigma = Decimal(str(stdev(values)))
    z = Decimal(str(NormalDist().inv_cdf(float(service_level))))
    units = int((z * sigma * Decimal(lead_time_days).sqrt()).to_integral_value(rounding=ROUND_CEILING))
    return SafetyStock(
        "ok",
        units=max(0, units),
        service_level=service_level,
        daily_std_dev=sigma.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        z_score=z.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        days_used=len(values),
        days_censored=censored,
    )


def product_service_level(specifications: dict | None, default: Decimal) -> Decimal:
    """Per-product override from specifications["reorder_service_level"] (0.5–0.999), else the default."""
    raw = (specifications or {}).get("reorder_service_level")
    try:
        value = Decimal(str(raw)) if raw is not None else None
    except ArithmeticError:
        value = None
    return value if value is not None and Decimal("0.5") < value <= Decimal("0.999") else default
