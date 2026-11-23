"""Category-pooled price elasticity with partial pooling (Phase 5.1).

Pure functions only: no database, no network. The offline task in
``pooled_elasticity_service`` loads seller-scoped data and persists results.

Model, per seller and category, on daily product panels:

    ln(units + a) = product_effect + elasticity * ln(price)
                    + weekday effects + promotion effect + error

Product effects are removed by within-product demeaning. Stocked-out days are
left out: a day that ended with no stock available may have lost sales. Each product's own slope is shrunk toward the
category slope by observation count: w = n / (n + k).

The out-of-time check fits on all days before the last ``holdout_days`` and
predicts held-out daily units. It passes only when the holdout has enough days,
shows price variation, and the model beats a no-price-effect baseline by at
least ``min_improvement_rate`` in mean absolute error.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import exp, log
from uuid import UUID

POOLED_VERSION = "pooled-v1"
WEEKDAYS = 7
# ln(price), six weekday dummies (Monday is the baseline), promotion.
FEATURE_NAMES = ["log_price", "tue", "wed", "thu", "fri", "sat", "sun", "promotion"]


@dataclass(frozen=True)
class DailyPoint:
    product_id: UUID
    day: date
    price: Decimal
    units: int
    promotion: bool


@dataclass(frozen=True)
class PooledConfig:
    zero_unit_adjustment: Decimal
    min_elasticity: Decimal
    max_elasticity: Decimal
    pooling_strength: int
    min_product_days: int
    min_price_variation_rate: Decimal
    holdout_days: int
    min_holdout_days: int
    min_improvement_rate: Decimal


@dataclass
class CategoryFit:
    elasticity: float
    coefficients: list[float]
    observation_count: int
    product_count: int
    r_squared: float


@dataclass
class ProductEstimate:
    product_id: UUID
    elasticity: Decimal
    own_elasticity: Decimal | None
    observation_count: int
    shrink_weight: Decimal
    observation_start: date
    observation_end: date
    baseline_units: Decimal
    metrics: dict[str, object] = field(default_factory=dict)


@dataclass
class CategoryResult:
    fit: CategoryFit | None
    products: list[ProductEstimate]
    out_of_time: dict[str, object]
    reasons: list[str]


def build_daily_panel(
    sales: list[tuple[UUID, date, Decimal, int, bool]],
    censored: dict[UUID, set[date]],
) -> list[DailyPoint]:
    """Aggregate valid sales rows (product, day, unit price, net units, promotion) into daily points.

    The daily price is the unit-weighted average transaction price. Censored days
    (ended with no stock) are dropped.
    """
    grouped: dict[tuple[UUID, date], list[tuple[Decimal, int, bool]]] = defaultdict(list)
    for product_id, day, price, units, promotion in sales:
        if price > 0 and units >= 0:
            grouped[(product_id, day)].append((price, units, promotion))
    points = []
    for (product_id, day), rows in sorted(grouped.items(), key=lambda item: (str(item[0][0]), item[0][1])):
        if day in censored.get(product_id, set()):
            continue
        units = sum(row[1] for row in rows)
        if units <= 0:
            continue
        price = sum(row[0] * row[1] for row in rows) / Decimal(units)
        points.append(DailyPoint(product_id, day, price, units, any(row[2] for row in rows)))
    return points


def censored_days(available_by_day: dict[date, int]) -> set[date]:
    """Days that ended with nothing available: sales that day may be cut short by the stockout.

    Days without a snapshot are unknown and kept.
    """
    return {day for day, available in available_by_day.items() if available <= 0}


def fit_category(points: list[DailyPoint], config: PooledConfig) -> CategoryResult:
    reasons: list[str] = []
    if not points:
        return CategoryResult(None, [], {"status": "not_run", "passed": False, "reason": "no_observations"}, ["no_observations"])

    out_of_time = evaluate_out_of_time(points, config)
    fit = _fit(points, config)
    if fit is None:
        reasons.append("insufficient_price_variation_across_category")
        return CategoryResult(None, [], out_of_time, reasons)

    category_slope = _clamp(Decimal(str(fit.elasticity)), config)
    products: list[ProductEstimate] = []
    by_product = _group(points)
    for product_id, rows in by_product.items():
        own = _own_slope(rows, fit, config) if _eligible(rows, config) else None
        own_slope = _clamp(Decimal(str(own[0])), config) if own else None
        n = len(rows)
        weight = Decimal(n) / Decimal(n + config.pooling_strength) if own_slope is not None else Decimal("0")
        blended = category_slope if own_slope is None else weight * own_slope + (Decimal("1") - weight) * category_slope
        products.append(
            ProductEstimate(
                product_id=product_id,
                elasticity=_q6(_clamp(blended, config)),
                own_elasticity=_q6(own_slope) if own_slope is not None else None,
                observation_count=n,
                shrink_weight=_q4(weight),
                observation_start=min(row.day for row in rows),
                observation_end=max(row.day for row in rows),
                baseline_units=_q4(Decimal(sum(row.units for row in rows)) / Decimal(n)),
                metrics={"own_fit_r_squared": round(own[1], 4) if own else None},
            )
        )
    return CategoryResult(fit, products, out_of_time, reasons)


def evaluate_out_of_time(points: list[DailyPoint], config: PooledConfig) -> dict[str, object]:
    last_day = max(point.day for point in points)
    cutoff = last_day - timedelta(days=config.holdout_days)
    train = [point for point in points if point.day <= cutoff]
    holdout = [point for point in points if point.day > cutoff]
    summary: dict[str, object] = {
        "status": "evaluated",
        "passed": False,
        "cutoff": cutoff.isoformat(),
        "train_days": len({point.day for point in train}),
        "holdout_days": len({point.day for point in holdout}),
        "holdout_observations": len(holdout),
        "min_improvement_rate": str(config.min_improvement_rate),
    }
    if summary["holdout_days"] < config.min_holdout_days:  # type: ignore[operator]
        return {**summary, "status": "not_run", "reason": "insufficient_holdout_days"}
    if not _has_price_variation(holdout, config.min_price_variation_rate):
        # A price-response claim cannot be validated without price changes in the holdout.
        return {**summary, "status": "not_run", "reason": "no_price_variation_in_holdout"}
    fit = _fit(train, config)
    if fit is None:
        return {**summary, "status": "not_run", "reason": "insufficient_training_price_variation"}

    train_by_product = _group(train)
    model_errors: list[float] = []
    naive_errors: list[float] = []
    for point in holdout:
        history = train_by_product.get(point.product_id)
        if not history:
            continue
        mean_y = sum(_y(row, config) for row in history) / len(history)
        mean_x = [sum(column) / len(history) for column in zip(*(_x(row) for row in history))]
        x = _x(point)
        predicted_log = mean_y + sum(b * (value - mean) for b, value, mean in zip(fit.coefficients, x, mean_x))
        adjustment = float(config.zero_unit_adjustment)
        predicted = max(0.0, exp(predicted_log) - adjustment)
        naive = max(0.0, exp(mean_y) - adjustment)
        model_errors.append(abs(predicted - point.units))
        naive_errors.append(abs(naive - point.units))
    if not model_errors:
        return {**summary, "status": "not_run", "reason": "no_holdout_products_with_training_history"}
    model_mae = sum(model_errors) / len(model_errors)
    naive_mae = sum(naive_errors) / len(naive_errors)
    improvement = (naive_mae - model_mae) / naive_mae if naive_mae > 0 else 0.0
    passed = improvement >= float(config.min_improvement_rate)
    return {
        **summary,
        "train_elasticity": round(fit.elasticity, 6),
        "model_mae_units": round(model_mae, 4),
        "naive_mae_units": round(naive_mae, 4),
        "improvement_rate": round(improvement, 4),
        "passed": passed,
        "reason": None if passed else "did_not_beat_no_price_effect_baseline",
    }


def _fit(points: list[DailyPoint], config: PooledConfig) -> CategoryFit | None:
    by_product = _group(points)
    rows: list[list[float]] = []
    targets: list[float] = []
    for product_rows in by_product.values():
        xs = [_x(row) for row in product_rows]
        ys = [_y(row, config) for row in product_rows]
        x_mean = [sum(column) / len(xs) for column in zip(*xs)]
        y_mean = sum(ys) / len(ys)
        for x, y in zip(xs, ys):
            rows.append([value - mean for value, mean in zip(x, x_mean)])
            targets.append(y - y_mean)
    if len(rows) <= len(FEATURE_NAMES) or sum(row[0] ** 2 for row in rows) < 1e-9:
        return None
    # Drop controls that never vary (e.g. no promotions); the normal equations would be singular.
    active = [index for index in range(len(FEATURE_NAMES)) if any(abs(row[index]) > 1e-12 for row in rows)]
    if 0 not in active:
        return None
    reduced = [[row[index] for index in active] for row in rows]
    solved = _least_squares(reduced, targets)
    if solved is None:
        return None
    coefficients = [0.0] * len(FEATURE_NAMES)
    for index, value in zip(active, solved):
        coefficients[index] = value
    predictions = [sum(c * v for c, v in zip(coefficients, row)) for row in rows]
    sse = sum((t - p) ** 2 for t, p in zip(targets, predictions))
    sst = sum(t**2 for t in targets)
    return CategoryFit(
        elasticity=coefficients[0],
        coefficients=coefficients,
        observation_count=len(rows),
        product_count=len(by_product),
        r_squared=1 - sse / sst if sst else 0.0,
    )


def _own_slope(rows: list[DailyPoint], category: CategoryFit, config: PooledConfig) -> tuple[float, float] | None:
    """Product's own price slope, with weekday and promotion effects held at the category estimates."""
    xs = [_x(row) for row in rows]
    prices = [x[0] for x in xs]
    adjusted = [_y(row, config) - sum(c * v for c, v in zip(category.coefficients[1:], x[1:])) for row, x in zip(rows, xs)]
    x_mean = sum(prices) / len(prices)
    y_mean = sum(adjusted) / len(adjusted)
    variance = sum((x - x_mean) ** 2 for x in prices)
    if variance < 1e-9:
        return None
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(prices, adjusted)) / variance
    sse = sum((y - y_mean - slope * (x - x_mean)) ** 2 for x, y in zip(prices, adjusted))
    sst = sum((y - y_mean) ** 2 for y in adjusted)
    return slope, (1 - sse / sst if sst else 0.0)


def _least_squares(rows: list[list[float]], targets: list[float]) -> list[float] | None:
    """Solve (XᵀX)b = Xᵀy by Gaussian elimination with partial pivoting."""
    size = len(rows[0])
    matrix = [[sum(row[i] * row[j] for row in rows) for j in range(size)] for i in range(size)]
    vector = [sum(row[i] * t for row, t in zip(rows, targets)) for i in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda r: abs(matrix[r][column]))
        if abs(matrix[pivot][column]) < 1e-12:
            return None
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        vector[column], vector[pivot] = vector[pivot], vector[column]
        for row in range(column + 1, size):
            factor = matrix[row][column] / matrix[column][column]
            for k in range(column, size):
                matrix[row][k] -= factor * matrix[column][k]
            vector[row] -= factor * vector[column]
    solution = [0.0] * size
    for row in range(size - 1, -1, -1):
        solution[row] = (vector[row] - sum(matrix[row][k] * solution[k] for k in range(row + 1, size))) / matrix[row][row]
    return solution


def _x(point: DailyPoint) -> list[float]:
    weekday = [1.0 if point.day.weekday() == index else 0.0 for index in range(1, WEEKDAYS)]
    return [log(float(point.price)), *weekday, 1.0 if point.promotion else 0.0]


def _y(point: DailyPoint, config: PooledConfig) -> float:
    return log(float(Decimal(point.units) + config.zero_unit_adjustment))


def _group(points: list[DailyPoint]) -> dict[UUID, list[DailyPoint]]:
    grouped: dict[UUID, list[DailyPoint]] = defaultdict(list)
    for point in points:
        grouped[point.product_id].append(point)
    return grouped


def _eligible(rows: list[DailyPoint], config: PooledConfig) -> bool:
    return len(rows) >= config.min_product_days and _has_price_variation(rows, config.min_price_variation_rate)


def _has_price_variation(points: list[DailyPoint], min_rate: Decimal) -> bool:
    for rows in _group(points).values():
        prices = [row.price for row in rows]
        if min(prices) > 0 and (max(prices) - min(prices)) / min(prices) >= min_rate:
            return True
    return False


def _clamp(value: Decimal, config: PooledConfig) -> Decimal:
    return max(config.min_elasticity, min(config.max_elasticity, value))


def _q4(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _q6(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
