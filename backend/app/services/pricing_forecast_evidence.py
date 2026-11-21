"""Read baseline forecast and observational price-response evidence for pricing."""

import logging
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from threading import BoundedSemaphore
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.product_price_history import (
    ProductPriceHistory,
    ProductPriceHistorySource,
)
from app.models.promotion import PromotionResult
from app.schemas.forecast_features import ForecastSourceSnapshot
from app.schemas.forecast_inference import ForecastMode
from app.schemas.statistical_forecast import BaselineConfig
from app.scraper.constants import MARKETPLACE_NAME
from app.services.forecast_feature_builder import eligible_observed_sales
from app.services.forecast_inference_service import ForecastInferenceService
from app.services.forecast_snapshot_service import (
    ForecastSnapshotService,
    forecast_read_session,
)
from app.services.historical_dataset_service import BUSINESS_TIMEZONE, DAY, _opening
from app.services.statistical_forecast_service import _supports_weekly_seasonality

logger = logging.getLogger(__name__)
PRICING_FORECAST_VERSION = "forecast-pricing-v1"
PRICING_HORIZON_DAYS: Final = 30
_CAPACITY = BoundedSemaphore(1)


def unavailable_pricing_evidence(reason: str) -> dict[str, Any]:
    return {
        "baseline_demand_forecast": {"status": "UNAVAILABLE", "reason": reason},
        "historical_price_demand_association": {
            "status": "UNAVAILABLE",
            "reason": reason,
        },
        "price_response": {
            "status": "UNKNOWN",
            "reason": "PRICE_RESPONSE_VALIDATION_UNAVAILABLE",
        },
    }


def load_pricing_forecast_evidence(
    db: Session,
    *,
    seller_id: UUID,
    product_id: UUID,
    current_price: Decimal,
    evaluated_at: datetime,
) -> dict[str, Any]:
    bind = db.get_bind()
    if not isinstance(bind, Engine) or bind.dialect.name != "postgresql":
        return unavailable_pricing_evidence("FORECAST_CAPTURE_UNAVAILABLE")
    if not _CAPACITY.acquire(blocking=False):
        return unavailable_pricing_evidence("FORECAST_CAPTURE_BUSY")
    try:
        day = evaluated_at.astimezone(BUSINESS_TIMEZONE).date()
        config = BaselineConfig()
        start = day - config.lookback_days * DAY
        with forecast_read_session(db) as read:
            snapshot = ForecastSnapshotService(
                read, authorized_seller_id=seller_id
            ).capture(
                product_id=product_id,
                start_date=start,
                end_date=day - DAY,
                as_of=evaluated_at,
            )
            edit_days, promotion_results = _history_conditions(
                read, seller_id, product_id, start, evaluated_at
            )
        evidence = unavailable_pricing_evidence("NO_USABLE_APPROVED_MODEL")
        evidence["historical_price_demand_association"] = describe_price_history(
            snapshot, edit_days=edit_days, promotion_results=promotion_results
        )
        origin = snapshot.captured_at + timedelta(microseconds=1)
        if not (
            evaluated_at <= origin <= evaluated_at + timedelta(seconds=30)
            and origin.astimezone(BUSINESS_TIMEZONE).date() == day
            and snapshot.catalog.base_price == current_price
        ):
            evidence["baseline_demand_forecast"]["reason"] = (
                "FORECAST_ORIGIN_OR_PRICE_CHANGED"
            )
            return evidence
        evidence["baseline_demand_forecast"] = _baseline_evidence(
            snapshot, origin, config
        )
        return evidence
    except (SQLAlchemyError, ValueError, PermissionError, LookupError) as exc:
        logger.warning(
            "pricing_forecast_evidence_unavailable error_type=%s", type(exc).__name__
        )
        return unavailable_pricing_evidence("FORECAST_EVIDENCE_UNAVAILABLE")
    finally:
        _CAPACITY.release()


def _baseline_evidence(
    snapshot: ForecastSourceSnapshot, origin: datetime, config: BaselineConfig
) -> dict[str, Any]:
    if os.getenv("FORECAST_ML_MODE") != ForecastMode.ENABLED:
        return {"status": "UNAVAILABLE", "reason": "APPROVED_INFERENCE_DISABLED"}
    try:
        inference = ForecastInferenceService.enabled_runtime(snapshot.seller_id, config)
    except ValueError:
        return {"status": "UNAVAILABLE", "reason": "INVALID_INFERENCE_CONFIGURATION"}
    result = inference.forecast(
        snapshot, forecast_origin=origin, horizon_days=PRICING_HORIZON_DAYS
    )
    point = result.forecast
    if (
        result.mode != ForecastMode.ENABLED
        or result.source not in {"active", "previous"}
        or point.model_name != "catboost"
        or point.expected_units is None
        or (
            point.seller_id,
            point.product_id,
            point.horizon_days,
            point.forecast_origin,
        )
        != (snapshot.seller_id, snapshot.product_id, PRICING_HORIZON_DAYS, origin)
    ):
        return {
            "status": "UNAVAILABLE",
            "reason": result.selection_reason,
            "attempts": [
                attempt.model_dump(mode="json") for attempt in result.attempts
            ],
        }
    return {
        "status": "AVAILABLE",
        "source": result.source,
        "metric": "product_net_units_sold",
        "observed_base_price": str(snapshot.catalog.base_price),
        "currency": snapshot.catalog.currency,
        "assumption": "Forecast uses the observed catalog and historical sales features.",
        "forecast": point.model_dump(mode="json"),
        "uncertainty": (
            point.prediction_interval.model_dump(mode="json")
            if point.prediction_interval
            else {"status": "uncalibrated", "reason": "MODEL_INTERVAL_UNAVAILABLE"}
        ),
    }


def _history_conditions(
    db: Session, seller_id: UUID, product_id: UUID, start: date, cutoff: datetime
) -> tuple[set[date], bool]:
    edits = db.scalars(
        select(ProductPriceHistory.changed_at)
        .where(
            ProductPriceHistory.seller_id == seller_id,
            ProductPriceHistory.product_id == product_id,
            ProductPriceHistory.marketplace.is_(None),
            ProductPriceHistory.listing_id.is_(None),
            ProductPriceHistory.currency == "BDT",
            ProductPriceHistory.source == ProductPriceHistorySource.PRODUCT_EDIT,
            ProductPriceHistory.old_price > 0,
            ProductPriceHistory.new_price > 0,
            ProductPriceHistory.old_price != ProductPriceHistory.new_price,
            ProductPriceHistory.changed_at >= _opening(start),
            ProductPriceHistory.changed_at <= ProductPriceHistory.created_at,
            ProductPriceHistory.created_at < cutoff,
        )
        .distinct()
    )
    edit_days = {time.astimezone(BUSINESS_TIMEZONE).date() for time in edits}
    promotion = db.scalar(
        select(PromotionResult.id)
        .where(
            PromotionResult.seller_id == seller_id,
            PromotionResult.product_id == product_id,
            PromotionResult.started_at < cutoff,
            PromotionResult.ended_at >= _opening(start),
            PromotionResult.created_at < cutoff,
            PromotionResult.updated_at < cutoff,
        )
        .limit(1)
    )
    return edit_days, promotion is not None


def describe_price_history(
    snapshot: ForecastSourceSnapshot, *, edit_days: set[date], promotion_results: bool
) -> dict[str, Any]:
    rows = snapshot.history.rows
    daily_units = {row.business_date: eligible_observed_sales(row) for row in rows}
    groups: dict[Decimal, list[int]] = defaultdict(list)
    for row in rows:
        units = daily_units[row.business_date]
        price = row.effective_selling_price
        if (
            units is not None
            and price is not None
            and price > 0
            and row.currency == "BDT"
            and row.marketplace == MARKETPLACE_NAME
            and row.promotion_indicator is not True
        ):
            groups[price].append(units)
    prices = sorted(groups)
    priced_days = sum(map(len, groups.values()))
    span = (prices[-1] - prices[0]) / prices[0] if prices else None
    # This is a sample screen for descriptive evidence only. Transaction
    # averages can change within an unchanged offer because of order mix.
    sufficient_variation = (
        len(edit_days) >= 4
        and len(prices) >= 3
        and priced_days >= 28
        and span is not None
        and span >= Decimal("0.05")
    )
    recent_days = [snapshot.history.end_date - i * DAY for i in range(55, -1, -1)]
    recent = [daily_units.get(day) for day in recent_days]
    comparable = tuple(units for units in recent if units is not None)
    seasonality = (
        _supports_weekly_seasonality(comparable, BaselineConfig())
        if len(comparable) == len(recent)
        else None
    )
    trend = None
    if len(comparable) == len(recent):
        older, newer = sum(comparable[:28]), sum(comparable[28:])
        trend = {
            "previous_28d_units": older,
            "recent_28d_units": newer,
            "material_shift": abs(newer - older) > 0
            and Decimal(abs(newer - older)) >= Decimal(older) * Decimal("0.20"),
        }

    market_means = {
        row.business_date: stats.mean
        for row in rows
        for stats in row.competitor_prices
        if stats.marketplace == MARKETPLACE_NAME and stats.currency == "BDT"
    }
    comparable_edits = [
        day for day in edit_days if day in market_means and day + DAY in market_means
    ]
    coincident = sum(
        market_means[day] != market_means[day + DAY] for day in comparable_edits
    )
    return {
        "status": "OBSERVATIONAL_ONLY"
        if len(prices) >= 2
        else "INSUFFICIENT_PRICE_VARIATION",
        "dataset_version": snapshot.history.version,
        "start": snapshot.history.start_date.isoformat(),
        "end": snapshot.history.end_date.isoformat(),
        "data_cutoff": snapshot.history.as_of_timestamp.isoformat(),
        "currency": "BDT",
        "marketplace": MARKETPLACE_NAME,
        "priced_days": priced_days,
        "distinct_transaction_daily_prices": len(prices),
        "recorded_base_price_edit_days": len(edit_days),
        "relative_price_span": str(span) if span is not None else None,
        "variation_screen": "SUFFICIENT_FOR_DESCRIPTIVE_REVIEW"
        if sufficient_variation
        else "INSUFFICIENT_PRICE_VARIATION",
        "observations": [
            {
                "daily_transaction_price": str(price),
                "days": len(groups[price]),
                "mean_net_units_per_day": str(
                    Decimal(sum(groups[price])) / len(groups[price])
                ),
            }
            for price in prices
        ],
        "confounders": {
            "promotion_observed": True
            if promotion_results or any(row.promotion_indicator is True for row in rows)
            else None,
            "promotion_unknown_days": sum(
                row.promotion_indicator is None for row in rows
            ),
            "weekly_seasonality_signal": seasonality,
            "stockout_days": sum(row.stockout_indicator is True for row in rows),
            "unknown_stockout_days": sum(
                row.stockout_indicator is None for row in rows
            ),
            "sales_coverage_incomplete_days": sum(
                not row.sales_coverage_complete for row in rows
            ),
            "demand_trend": trend,
            "edit_days_with_market_comparison": len(comparable_edits),
            "concurrent_competitor_aggregate_movements": coincident
            if comparable_edits
            else None,
        },
    }
