from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key
from math import floor, isfinite

DEFAULT_PRICE_ELASTICITY = -1.2
SIMILAR_PROFIT_TOLERANCE_RATE = 0.005
BELOW_UNIT_COST_WARNING = "Price is below unit cost"


@dataclass(frozen=True)
class RevenueSimulatorInput:
    candidate_prices: list[float]
    unit_cost: float
    baseline_price: float
    baseline_monthly_units: float
    product_id: str | None = None
    product_name: str | None = None
    price_elasticity: float = DEFAULT_PRICE_ELASTICITY


def calculate_revenue_simulation(input_data: RevenueSimulatorInput) -> dict[str, object]:
    """Calculate revenue simulations without database, AI, or external calls."""
    candidate_prices = _normalize_candidate_prices(input_data.candidate_prices)
    price_elasticity = input_data.price_elasticity

    simulations = [
        _simulate_price(
            candidate_price=price,
            unit_cost=input_data.unit_cost,
            baseline_price=input_data.baseline_price,
            baseline_monthly_units=input_data.baseline_monthly_units,
            price_elasticity=price_elasticity,
        )
        for price in candidate_prices
    ]

    baseline_revenue = _round_money(input_data.baseline_price * input_data.baseline_monthly_units)
    baseline_profit = _round_money(
        (input_data.baseline_price - input_data.unit_cost)
        * input_data.baseline_monthly_units
    )
    baseline_margin = _round_money(
        (baseline_profit / baseline_revenue) * 100 if baseline_revenue > 0 else 0
    )
    baseline = {
        "price": input_data.baseline_price,
        "estimatedUnits": _round_units(input_data.baseline_monthly_units),
        "revenue": baseline_revenue,
        "profit": baseline_profit,
        "margin": baseline_margin,
    }

    recommended_simulation = recommend_best_price(simulations)
    return {
        "simulations": simulations,
        "recommendedPrice": recommended_simulation["price"],
        "recommendedSimulation": recommended_simulation,
        "baseline": baseline,
        "expectedRevenueImpact": calculate_impact_percentage(
            recommended_simulation["revenue"], baseline_revenue
        ),
        "expectedProfitImpact": calculate_impact_percentage(
            recommended_simulation["profit"], baseline_profit
        ),
    }


def recommend_best_price(simulations: list[dict[str, object]]) -> dict[str, object]:
    if not simulations:
        raise ValueError("simulations must be a non-empty array.")
    return sorted(simulations, key=cmp_to_key(_compare_simulations))[0]


def calculate_impact_percentage(new_value: float, old_value: float) -> str:
    if not _is_finite_number(new_value) or not _is_finite_number(old_value):
        raise ValueError("Impact values must be finite numbers.")
    if old_value == 0:
        if new_value == 0:
            return "+0.00%"
        return "+100.00%" if new_value > 0 else "-100.00%"
    impact = ((new_value - old_value) / abs(old_value)) * 100
    return f"{'+' if impact >= 0 else ''}{_round_money(impact):.2f}%"


def _simulate_price(
    *,
    candidate_price: float,
    unit_cost: float,
    baseline_price: float,
    baseline_monthly_units: float,
    price_elasticity: float,
) -> dict[str, object]:
    # Demand estimate: lower prices usually increase units when elasticity is negative.
    estimated_units = _round_units(
        baseline_monthly_units * ((candidate_price / baseline_price) ** price_elasticity)
    )
    revenue = _round_money(candidate_price * estimated_units)
    profit = _round_money((candidate_price - unit_cost) * estimated_units)
    margin = _round_money((profit / revenue) * 100 if revenue > 0 else 0)
    simulation: dict[str, object] = {
        "price": candidate_price,
        "estimatedUnits": estimated_units,
        "revenue": revenue,
        "profit": profit,
        "margin": margin,
    }
    if candidate_price < unit_cost:
        simulation["warning"] = BELOW_UNIT_COST_WARNING
    return simulation


def _compare_simulations(first: dict[str, object], second: dict[str, object]) -> int:
    first_profit = float(first["profit"])
    second_profit = float(second["profit"])
    tolerance = (
        max(abs(first_profit), abs(second_profit), 1)
        * SIMILAR_PROFIT_TOLERANCE_RATE
    )
    if abs(first_profit - second_profit) > tolerance:
        return -1 if first_profit > second_profit else 1

    first_margin = float(first["margin"])
    second_margin = float(second["margin"])
    if first_margin != second_margin:
        return -1 if first_margin > second_margin else 1

    first_price = float(first["price"])
    second_price = float(second["price"])
    if first_price == second_price:
        return 0
    return -1 if first_price < second_price else 1


def _normalize_candidate_prices(candidate_prices: list[float]) -> list[float]:
    if not candidate_prices:
        raise ValueError("candidatePrices must contain at least one valid price.")
    if any(not _is_finite_number(price) or price <= 0 for price in candidate_prices):
        raise ValueError("candidatePrices must contain positive numbers only.")
    return sorted({_round_money(price) for price in candidate_prices})


def _is_finite_number(value: float) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and isfinite(value)


def _round_money(value: float) -> float:
    return round(value + 1e-12, 2)


def _round_units(value: float) -> int:
    return floor(value + 0.5)
