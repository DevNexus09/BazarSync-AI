"""Task 9 feature encoding shared by training and native inference."""

from decimal import Decimal
import math
import statistics

from app.schemas.forecast_features import (
    FEATURE_SCHEMA_SHA256,
    FEATURE_VERSION,
    ForecastFeatureRow,
)
from app.services.historical_dataset_service import BUSINESS_TIMEZONE, DAY

CATBOOST_VERSION = "1.2.10"
MODEL_VERSION = "catboost-demand-v1"
ENCODER_VERSION = "catboost-features-v1"
MISSING_CATEGORY = "__MISSING__"


def _number(value: Decimal | int | float | bool | None) -> float:
    if value is None:
        return math.nan
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Numeric forecast features must be finite when present.")
    return result


def flatten_feature_row(row: ForecastFeatureRow) -> dict[str, float | str]:
    """Map the versioned Task 9 payload to a stable CatBoost row."""
    if row.schema_sha256 != FEATURE_SCHEMA_SHA256 or row.version != FEATURE_VERSION:
        raise ValueError("Unsupported Task 9 feature schema.")
    if (
        row.feature_date != row.forecast_origin.astimezone(BUSINESS_TIMEZONE).date()
        or row.target_start_date != row.feature_date + DAY
        or row.target_end_date != row.feature_date + row.horizon_days * DAY
        or not row.extract_cutoff <= row.data_cutoff < row.forecast_origin
    ):
        raise ValueError("Invalid forecast origin, cutoff, or target window.")
    f = row.features
    if len(f.target_calendar) != row.horizon_days:
        raise ValueError("Target calendar length must equal the explicit horizon.")
    values: dict[str, float | str] = {}
    for name in ("sales_lag_1d", "sales_lag_7d", "sales_lag_14d", "sales_lag_28d"):
        values[name] = _number(getattr(f, name))
    for days in (7, 14, 30):
        window = getattr(f, f"rolling_{days}d")
        for name in (
            "observed_days",
            "total_units",
            "population_stddev",
            "zero_sales_percent",
        ):
            values[f"rolling_{days}d_{name}"] = _number(getattr(window, name))
    values.update(
        category=f.category or MISSING_CATEGORY,
        brand=f.brand or MISSING_CATEGORY,
        product_age_days=_number(f.product_age_days),
        known_base_price=_number(f.known_base_price),
        price_currency=f.price_currency or MISSING_CATEGORY,
        latest_base_price_change=_number(f.latest_base_price_change),
        latest_price_change_age_days=(
            _number(
                (row.forecast_origin - f.latest_price_change_at).total_seconds() / 86400
            )
            if f.latest_price_change_at is not None
            else math.nan
        ),
    )
    calendar = f.feature_calendar
    for name in ("day_of_week", "month", "weekend", "month_end", "public_holiday"):
        values[f"feature_calendar_{name}"] = _number(getattr(calendar, name))
    for index, target in enumerate(f.target_calendar, start=1):
        for name in ("day_of_week", "month", "weekend", "month_end", "public_holiday"):
            values[f"target_{index}_{name}"] = _number(getattr(target, name))
    markets = f.competitor_markets
    medians = [
        float(item.median_price)
        for item in markets
        if f.price_currency is not None and item.currency == f.price_currency
    ]
    values.update(
        competitor_market_signature=(
            "|".join(sorted(f"{item.marketplace}:{item.currency}" for item in markets))
            or MISSING_CATEGORY
        ),
        competitor_market_count=_number(len(markets)),
        competitor_listing_count=_number(sum(item.listing_count for item in markets)),
        competitor_median_mean=_number(statistics.fmean(medians) if medians else None),
        competitor_median_min=_number(min(medians) if medians else None),
        competitor_median_max=_number(max(medians) if medians else None),
        competitor_newest_age_seconds=_number(
            min((item.newest_observation_age_seconds for item in markets), default=None)
        ),
        competitor_oldest_age_seconds=_number(
            max((item.oldest_observation_age_seconds for item in markets), default=None)
        ),
        competitor_price_gap=_number(f.competitor_price_gap),
        previous_day_on_hand=_number(f.previous_day_on_hand),
        previous_day_stockout=_number(f.previous_day_stockout),
        inventory_observed_days_30d=_number(f.inventory_observed_days_30d),
        stockout_days_30d=_number(f.stockout_days_30d),
        previous_day_promotion=_number(f.previous_day_promotion),
        previous_day_discount=_number(f.previous_day_discount),
        quality_usable_sales_days_30d=_number(row.quality.usable_sales_days_30d),
        quality_sufficient_history=_number(row.quality.sufficient_history),
        quality_flags="|".join(sorted(row.quality.flags)) or "__NONE__",
    )
    return values
