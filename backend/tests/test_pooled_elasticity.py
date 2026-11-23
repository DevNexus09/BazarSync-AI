from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from math import exp, log
import random
from uuid import uuid4

from app.services.pooled_elasticity import (
    DailyPoint,
    PooledConfig,
    build_daily_panel,
    censored_days,
    evaluate_out_of_time,
    fit_category,
)

CONFIG = PooledConfig(
    zero_unit_adjustment=Decimal("0.5"),
    min_elasticity=Decimal("-5"),
    max_elasticity=Decimal("0"),
    pooling_strength=20,
    min_product_days=6,
    min_price_variation_rate=Decimal("0.05"),
    holdout_days=28,
    min_holdout_days=14,
    min_improvement_rate=Decimal("0.05"),
)
START = date(2026, 6, 1)  # a Monday
TRUE_ELASTICITY = -1.5


def synthetic(products: int = 3, days: int = 100, *, elasticity: float = TRUE_ELASTICITY, price_moves: bool = True, seed: int = 7, noise: float = 0.05):
    rng = random.Random(seed)
    points = []
    for index in range(products):
        product_id = uuid4()
        base_price = 100 + 50 * index
        for offset in range(days):
            day = START + timedelta(days=offset)
            # Price steps between three levels every week, so every window has price variation.
            level = [0.9, 1.0, 1.1][(offset // 7 + index) % 3] if price_moves else 1.0
            price = Decimal(str(round(base_price * level, 2)))
            promotion = offset % 30 in (10, 11)
            weekend = 0.3 if day.weekday() >= 5 else 0.0
            log_units = 4 + index * 0.5 + elasticity * log(float(price) / base_price) + weekend + (0.4 if promotion else 0) + rng.gauss(0, noise)
            points.append(DailyPoint(product_id, day, price, max(1, round(exp(log_units))), promotion))
    return points


def test_recovers_known_elasticity_with_weekday_and_promotion_controls():
    result = fit_category(synthetic(), CONFIG)

    assert result.fit is not None
    assert abs(result.fit.elasticity - TRUE_ELASTICITY) < 0.15
    assert result.fit.product_count == 3
    # Promotion and weekend lifts are absorbed by the controls, not the price slope.
    assert result.fit.coefficients[-1] > 0.25
    assert result.fit.coefficients[6] > 0.2  # Sunday


def test_sparse_product_is_shrunk_toward_the_category():
    points = synthetic(products=3)
    sparse_id = uuid4()
    # Eight days with an implausible own slope: mostly pooled toward the category.
    for offset in range(8):
        price = Decimal("100") if offset % 2 else Decimal("120")
        points.append(DailyPoint(sparse_id, START + timedelta(days=60 + offset), price, 10 if offset % 2 else 2, False))
    result = fit_category(points, CONFIG)
    sparse = next(item for item in result.products if item.product_id == sparse_id)

    assert sparse.observation_count == 8
    assert sparse.shrink_weight == Decimal("0.2857")  # 8 / (8 + 20)
    assert sparse.own_elasticity is not None
    category = Decimal(str(result.fit.elasticity))
    assert abs(sparse.elasticity - category) < abs(sparse.own_elasticity - category)


def test_product_without_price_variation_takes_the_category_slope():
    points = synthetic(products=2)
    flat_id = uuid4()
    points += [DailyPoint(flat_id, START + timedelta(days=offset), Decimal("80"), 5, False) for offset in range(30)]
    result = fit_category(points, CONFIG)
    flat = next(item for item in result.products if item.product_id == flat_id)

    assert flat.own_elasticity is None
    assert flat.shrink_weight == Decimal("0")
    assert abs(float(flat.elasticity) - result.fit.elasticity) < 1e-5


def test_out_of_time_passes_when_price_drives_demand():
    evaluation = evaluate_out_of_time(synthetic(), CONFIG)

    assert evaluation["status"] == "evaluated"
    assert evaluation["passed"] is True
    assert evaluation["model_mae_units"] < evaluation["naive_mae_units"]


def test_out_of_time_fails_when_price_does_not_drive_demand():
    evaluation = evaluate_out_of_time(synthetic(elasticity=0.0, noise=0.4), CONFIG)

    assert evaluation["passed"] is False


def test_out_of_time_not_run_without_price_variation_or_enough_days():
    assert evaluate_out_of_time(synthetic(price_moves=False), CONFIG)["reason"] == "no_price_variation_in_holdout"
    short = evaluate_out_of_time(synthetic(days=40), CONFIG)
    # 40 days: holdout is the last 28 days, but training needs earlier data with variation too.
    assert short["status"] in {"evaluated", "not_run"}
    tiny = evaluate_out_of_time(synthetic(days=10), CONFIG)
    assert tiny["passed"] is False


def test_no_variation_anywhere_gives_no_fit():
    result = fit_category(synthetic(price_moves=False), CONFIG)

    assert result.fit is None
    assert result.products == []
    assert "insufficient_price_variation_across_category" in result.reasons


def test_daily_panel_drops_censored_days_and_weights_price_by_units():
    product = uuid4()
    day = date(2026, 7, 1)
    panel = build_daily_panel(
        [
            (product, day, Decimal("100"), 3, False),
            (product, day, Decimal("110"), 1, True),
            (product, day + timedelta(days=1), Decimal("100"), 5, False),
            (product, day + timedelta(days=2), Decimal("0"), 5, False),  # invalid price
        ],
        {product: {day + timedelta(days=1)}},
    )

    assert len(panel) == 1
    assert panel[0].units == 4
    assert panel[0].price == Decimal("102.5")
    assert panel[0].promotion is True


def test_censored_days_are_days_that_ended_with_no_stock():
    day = date(2026, 7, 1)
    assert censored_days({day: 0, day + timedelta(days=1): 4, day + timedelta(days=2): -1}) == {day, day + timedelta(days=2)}
