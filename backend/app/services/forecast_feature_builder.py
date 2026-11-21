"""Build identical point-in-time features for training and inference."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Context, Decimal, localcontext
from statistics import median
from uuid import UUID

from app.schemas.forecast_features import (
    FEATURE_SCHEMA_SHA256,
    BangladeshHolidayCalendar,
    CalendarFeatures,
    CompetitorPriceObservation,
    ForecastFeatureQuality,
    ForecastFeatureRow,
    ForecastFeatures,
    ForecastHorizon,
    ForecastSourceSnapshot,
    ForecastTrainingExample,
    MarketFeatures,
    SalesWindow,
)
from app.services.bangladesh_holiday_calendar import BANGLADESH_CALENDARS
from app.services.historical_dataset_service import (
    BUSINESS_TIMEZONE,
    COMPETITOR_LOOKBACK,
    DATASET_VERSION,
    DAY,
    LABEL_BLOCKING_FLAGS,
    DailyBusinessRow,
    HistoricalDataset,
    _opening,
)


def eligible_observed_sales(row: DailyBusinessRow | None) -> int | None:
    if row is None or not row.forecast_label_eligible:
        return None
    if (
        not row.sales_coverage_complete
        or row.stockout_indicator is not False
        or not LABEL_BLOCKING_FLAGS.isdisjoint(row.data_quality_flags)
    ):
        raise ValueError("Inconsistent Task 8 sales eligibility.")
    units = row.observed_units_sold
    if units is None or units < 0:
        raise ValueError("Eligible Task 8 rows require a nonnegative sales label.")
    return units


def _rolling_windows(sales: tuple[int | None, ...]) -> dict[int, SalesWindow]:
    windows = {}
    count = total = squares = zeros = 0
    for days, units in enumerate(sales, start=1):
        if units is not None:
            count += 1
            total += units
            squares += units * units
            zeros += units == 0
        if days in (7, 14, 30):
            complete = count == days
            windows[days] = SalesWindow(
                days=days,
                observed_days=count,
                total_units=total if complete else None,
                population_stddev=(
                    Decimal(days * squares - total * total).sqrt() / days
                    if complete
                    else None
                ),
                zero_sales_percent=Decimal(100 * zeros) / days if complete else None,
            )
    return windows


def _market_features(
    observations: tuple[CompetitorPriceObservation, ...],
    cutoff: datetime,
    origin: datetime,
) -> tuple[MarketFeatures, ...]:
    # Apply availability before deduplication so a late refresh cannot mask an older observation.
    latest: dict[tuple[str, str], CompetitorPriceObservation] = {}
    for observation in observations:
        if not (
            origin - COMPETITOR_LOOKBACK
            <= observation.observed_at
            <= observation.available_at
            < cutoff
        ):
            continue
        key = (observation.marketplace, observation.listing)
        prior = latest.get(key)
        if prior is None or (
            observation.observed_at,
            observation.available_at,
            observation.snapshot_id,
        ) > (prior.observed_at, prior.available_at, prior.snapshot_id):
            latest[key] = observation
    groups = defaultdict(list)
    for observation in latest.values():
        groups[(observation.marketplace, observation.currency)].append(observation)
    return tuple(
        MarketFeatures(
            marketplace=marketplace,
            currency=currency,
            median_price=median([item.price for item in items]),
            listing_count=len(items),
            newest_observation_age_seconds=int(
                (origin - max(item.observed_at for item in items)).total_seconds()
            ),
            oldest_observation_age_seconds=int(
                (origin - min(item.observed_at for item in items)).total_seconds()
            ),
        )
        for (marketplace, currency), items in sorted(groups.items())
    )


@dataclass(frozen=True)
class OriginHistory:
    forecast_origin: datetime
    feature_date: date
    product_age_days: int
    # Positions are calendar days, starting at feature_date - 1.
    rows: tuple[DailyBusinessRow | None, ...]
    sales: tuple[int | None, ...]


class ForecastFeatureBuilder:
    def __init__(
        self,
        *,
        authorized_seller_id: UUID,
        calendars: tuple[BangladeshHolidayCalendar, ...] = BANGLADESH_CALENDARS,
    ) -> None:
        if len({calendar.version for calendar in calendars}) != len(calendars):
            raise ValueError("Duplicate holiday calendar version.")
        self._seller_id = authorized_seller_id
        self._calendars = tuple(
            sorted(
                (calendar.model_copy(deep=True) for calendar in calendars),
                key=lambda calendar: (calendar.published_at, calendar.version),
                reverse=True,
            )
        )

    def index_history(
        self,
        dataset: HistoricalDataset,
        product_id: UUID,
    ) -> dict[date, DailyBusinessRow]:
        if dataset.seller_id != self._seller_id:
            raise PermissionError("Forecast dataset outside authorized seller scope.")
        if (
            dataset.version != DATASET_VERSION
            or dataset.business_timezone != BUSINESS_TIMEZONE.key
        ):
            raise ValueError("Unsupported Task 8 dataset version or business timezone.")
        cutoff = dataset.as_of_timestamp
        if (
            cutoff.utcoffset() is None
            or not 0 <= (dataset.end_date - dataset.start_date).days < 366
            or _opening(dataset.end_date + DAY) > cutoff
        ):
            raise ValueError("Invalid Task 8 extract window.")
        index = {}
        for row in dataset.rows:
            if row.seller_id != self._seller_id or row.product_id != product_id:
                raise PermissionError(
                    "Forecast dataset must contain only the authorized seller product."
                )
            if (
                row.business_date in index
                or not dataset.start_date <= row.business_date <= dataset.end_date
                or row.as_of_timestamp != cutoff
                or row.prediction_cutoff != _opening(row.business_date)
            ):
                raise ValueError("Invalid or duplicate Task 8 daily row.")
            index[row.business_date] = row
        return index

    def _calendar(
        self,
        day: date,
        origin: datetime,
        versions: set[str],
    ) -> CalendarFeatures:
        holiday = None
        for calendar in self._calendars:
            if calendar.published_at < origin and day in calendar.holidays:
                holiday = calendar.holidays[day]
                versions.add(calendar.version)
                break
        weekday = day.weekday()
        return CalendarFeatures(
            day_of_week=weekday,
            month=day.month,
            weekend=weekday in (4, 5),
            month_end=(day + DAY).month != day.month,
            public_holiday=holiday,
        )

    def prepare_history(
        self,
        snapshot: ForecastSourceSnapshot,
        *,
        forecast_origin: datetime,
        lookback_days: int = 30,
        allow_empty: bool = False,
    ) -> OriginHistory:
        if not 1 <= lookback_days <= 366:
            raise ValueError("Lookback must be from 1 to 366 days.")
        if snapshot.seller_id != self._seller_id:
            raise PermissionError("Forecast snapshot outside authorized seller scope.")
        if forecast_origin.utcoffset() is None:
            raise ValueError("An aware forecast origin is required.")
        origin = forecast_origin.astimezone(timezone.utc)
        cutoff = snapshot.history.as_of_timestamp
        catalog = snapshot.catalog
        scope = (self._seller_id, snapshot.product_id)
        if (catalog.seller_id, catalog.product_id) != scope or any(
            (item.seller_id, item.product_id) != scope for item in snapshot.competitors
        ):
            raise PermissionError(
                "Forecast evidence outside authorized seller product scope."
            )
        if (
            cutoff.utcoffset() is None
            or not cutoff <= snapshot.captured_at < origin
            or not catalog.created_at <= catalog.updated_at < cutoff
        ):
            raise ValueError(
                "Forecast inputs must come from a snapshot captured before the forecast origin."
            )
        history = self.index_history(snapshot.history, snapshot.product_id)
        if not history and not allow_empty:
            raise ValueError("Forecast snapshot has no Task 8 product rows.")
        day = origin.astimezone(BUSINESS_TIMEZONE).date()
        previous = tuple(
            history.get(day - offset * DAY) for offset in range(1, lookback_days + 1)
        )
        return OriginHistory(
            forecast_origin=origin,
            feature_date=day,
            rows=previous,
            sales=tuple(eligible_observed_sales(row) for row in previous),
            product_age_days=(
                day - catalog.created_at.astimezone(BUSINESS_TIMEZONE).date()
            ).days,
        )

    def build(
        self,
        snapshot: ForecastSourceSnapshot,
        *,
        forecast_origin: datetime,
        horizon_days: ForecastHorizon,
        allow_empty: bool = False,
    ) -> ForecastFeatureRow:
        if horizon_days not in (7, 14, 30):
            raise ValueError("A 7, 14, or 30 day horizon is required.")
        prepared = self.prepare_history(
            snapshot,
            forecast_origin=forecast_origin,
            allow_empty=allow_empty,
        )
        origin, day = prepared.forecast_origin, prepared.feature_date
        previous, sales = prepared.rows, prepared.sales
        cutoff, catalog = snapshot.history.as_of_timestamp, snapshot.catalog
        versions: set[str] = set()
        feature_calendar = self._calendar(day, origin, versions)
        target_calendar = tuple(
            self._calendar(day + offset * DAY, origin, versions)
            for offset in range(1, horizon_days + 1)
        )
        last_day = previous[0]
        inventory_count = sum(
            row is not None and row.stockout_indicator is not None for row in previous
        )
        stockout_count = sum(
            row is not None and row.stockout_indicator is True for row in previous
        )
        price_change_known = (
            catalog.last_price_change is not None
            and catalog.price_history_id is not None
            and catalog.price_change_at is not None
            and catalog.price_change_recorded_at is not None
            and max(catalog.price_change_at, catalog.price_change_recorded_at) < cutoff
        )
        with localcontext(Context(prec=38)):
            windows = _rolling_windows(sales)
            markets = _market_features(snapshot.competitors, cutoff, origin)
            comparable = (
                markets[0]
                if len(markets) == 1 and markets[0].currency == catalog.currency
                else None
            )
            features = ForecastFeatures(
                sales_lag_1d=sales[0],
                sales_lag_7d=sales[6],
                sales_lag_14d=sales[13],
                sales_lag_28d=sales[27],
                rolling_7d=windows[7],
                rolling_14d=windows[14],
                rolling_30d=windows[30],
                category=catalog.category,
                brand=catalog.brand,
                product_age_days=prepared.product_age_days,
                known_base_price=catalog.base_price,
                price_currency=catalog.currency
                if catalog.base_price is not None
                else None,
                latest_base_price_change=catalog.last_price_change
                if price_change_known
                else None,
                latest_price_change_at=catalog.price_change_at.astimezone(timezone.utc)
                if price_change_known and catalog.price_change_at is not None
                else None,
                feature_calendar=feature_calendar,
                target_calendar=target_calendar,
                competitor_markets=markets,
                competitor_price_gap=(
                    catalog.base_price - comparable.median_price
                    if catalog.base_price is not None and comparable
                    else None
                ),
                previous_day_on_hand=last_day.on_hand_stock if last_day else None,
                previous_day_stockout=last_day.stockout_indicator if last_day else None,
                inventory_observed_days_30d=inventory_count,
                stockout_days_30d=stockout_count,
                previous_day_promotion=last_day.promotion_indicator
                if last_day
                else None,
                previous_day_discount=None,
            )
        sufficient = windows[7].observed_days == 7
        flags = tuple(
            flag
            for flag, applies in (
                ("INSUFFICIENT_RECENT_HISTORY", not sufficient),
                ("MISSING_SALES_DAYS", windows[30].observed_days < 30),
                ("MISSING_INVENTORY_DAYS", inventory_count < 30),
                ("STOCKOUT_OBSERVED", stockout_count > 0),
                ("MARKET_OBSERVATIONS_UNAVAILABLE", not markets),
                (
                    "CALENDAR_HISTORY_INCOMPLETE",
                    any(
                        item.public_holiday is None
                        for item in (feature_calendar, *target_calendar)
                    ),
                ),
            )
            if applies
        )
        return ForecastFeatureRow(
            schema_sha256=FEATURE_SCHEMA_SHA256,
            historical_dataset_version=snapshot.history.version,
            source_snapshot_version=snapshot.version,
            seller_id=self._seller_id,
            product_id=snapshot.product_id,
            feature_date=day,
            forecast_origin=origin,
            data_cutoff=snapshot.captured_at.astimezone(timezone.utc),
            extract_cutoff=cutoff.astimezone(timezone.utc),
            horizon_days=horizon_days,
            target_start_date=day + DAY,
            target_end_date=day + horizon_days * DAY,
            calendar_versions=tuple(sorted(versions)),
            features=features,
            quality=ForecastFeatureQuality(
                sufficient_history=sufficient,
                usable_sales_days_30d=windows[30].observed_days,
                flags=flags,
            ),
        )

    def build_training_example(
        self,
        snapshot: ForecastSourceSnapshot,
        *,
        forecast_origin: datetime,
        horizon_days: ForecastHorizon,
        outcomes: HistoricalDataset,
        allow_empty: bool = False,
    ) -> ForecastTrainingExample:
        feature_row = self.build(
            snapshot,
            forecast_origin=forecast_origin,
            horizon_days=horizon_days,
            allow_empty=allow_empty,
        )
        labels = self.index_history(outcomes, snapshot.product_id)
        eligible = [
            units
            for offset in range(horizon_days)
            if (
                units := eligible_observed_sales(
                    labels.get(feature_row.target_start_date + offset * DAY)
                )
            )
            is not None
        ]
        count = len(eligible)
        return ForecastTrainingExample(
            feature_row=feature_row,
            target_net_units=sum(eligible) if count == horizon_days else None,
            eligible_target_days=count,
            outcome_extract_cutoff=outcomes.as_of_timestamp,
        )
