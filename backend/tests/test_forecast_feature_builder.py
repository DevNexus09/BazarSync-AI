from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import AnyHttpUrl, ValidationError

from app.schemas.forecast_features import (
    FEATURE_SCHEMA_SHA256,
    BangladeshHolidayCalendar,
    CatalogSnapshot,
    CompetitorPriceObservation,
    ForecastFeatureRow,
    ForecastSourceSnapshot,
)
from app.services.bangladesh_holiday_calendar import BANGLADESH_CALENDARS
from app.services.forecast_feature_builder import ForecastFeatureBuilder
from app.services.historical_dataset_service import (
    DAY,
    DailyBusinessRow,
    HistoricalDataset,
    HistoricalDatasetQuality,
    _opening,
)

SELLER = UUID(int=1)
PRODUCT = UUID(int=2)
FEATURE_DATE = date(2025, 12, 15)
ORIGIN = _opening(FEATURE_DATE) + timedelta(hours=3)
CAPTURED = ORIGIN - timedelta(minutes=2)
EXTRACT_CUTOFF = ORIGIN - timedelta(minutes=3)


def task8_dataset(
    start,
    end,
    observation_cutoff,
    *,
    values=None,
    missing=(),
    stockouts=(),
    seller=SELLER,
):
    values = {} if values is None else values
    days = [start + i * DAY for i in range((end - start).days + 1)]
    rows = tuple(
        DailyBusinessRow(
            seller_id=seller,
            product_id=PRODUCT,
            business_date=day,
            prediction_cutoff=_opening(day),
            as_of_timestamp=observation_cutoff,
            observed_units_sold=values.get(day, 1),
            sales_coverage_complete=True,
            forecast_label_eligible=day not in stockouts,
            stockout_indicator=day in stockouts,
            on_hand_stock=0 if day in stockouts else 50,
            source_ids={},
        )
        for day in days
        if day not in missing
    )
    return HistoricalDataset(
        seller_id=seller,
        start_date=start,
        end_date=end,
        as_of_timestamp=observation_cutoff,
        rows=rows,
        quality=HistoricalDatasetQuality(
            row_count=len(rows),
            product_count=1,
            products_with_observed_sales=1,
            history_days=len(days),
            observed_days_by_product={},
            missing_values={},
            stockout_observed_days=len(stockouts),
            inventory_observed_days=len(rows),
            invalid_sales_records=0,
            negative_quantity_records=0,
            duplicate_sales_records=0,
            unkeyed_sales_records=0,
            category_distribution={},
            unknown_category_product_days=len(rows),
            eligible_product_days=len(rows) - len(stockouts),
            longest_eligible_run_by_product={},
        ),
    )


def snapshot(**overrides):
    return ForecastSourceSnapshot(
        **(
            {
                "seller_id": SELLER,
                "product_id": PRODUCT,
                "captured_at": CAPTURED,
                "catalog": CatalogSnapshot(
                    seller_id=SELLER,
                    product_id=PRODUCT,
                    created_at=_opening(FEATURE_DATE - 100 * DAY),
                    updated_at=EXTRACT_CUTOFF - DAY,
                    category="Books",
                    brand="Example",
                    base_price=Decimal("100.00"),
                    price_history_id=UUID(int=100),
                    last_price_change=Decimal("10.00"),
                    price_change_at=EXTRACT_CUTOFF - DAY,
                    price_change_recorded_at=EXTRACT_CUTOFF - DAY,
                ),
                "history": task8_dataset(
                    FEATURE_DATE - 30 * DAY, FEATURE_DATE - DAY, EXTRACT_CUTOFF
                ),
            }
            | overrides
        )
    )


def market(listing, price, observed_at, available_at, identifier, **overrides):
    return CompetitorPriceObservation(
        **(
            {
                "seller_id": SELLER,
                "product_id": PRODUCT,
                "marketplace": "Daraz Bangladesh",
                "listing": listing,
                "currency": "BDT",
                "price": Decimal(price),
                "snapshot_id": UUID(int=identifier),
                "observed_at": observed_at,
                "available_at": available_at,
            }
            | overrides
        )
    )


@pytest.fixture
def builder():
    return ForecastFeatureBuilder(authorized_seller_id=SELLER)


def test_lags_and_rolling_windows(builder):
    history = task8_dataset(
        FEATURE_DATE - 30 * DAY,
        FEATURE_DATE - DAY,
        EXTRACT_CUTOFF,
        values={FEATURE_DATE - offset * DAY: offset - 1 for offset in range(1, 31)},
    )
    row = builder.build(
        snapshot(history=history), forecast_origin=ORIGIN, horizon_days=7
    )
    features = row.features
    assert (
        features.sales_lag_1d,
        features.sales_lag_7d,
        features.sales_lag_14d,
        features.sales_lag_28d,
    ) == (0, 6, 13, 27)
    assert features.rolling_7d.total_units == 21
    assert features.rolling_7d.population_stddev == Decimal("2")
    assert abs(
        features.rolling_7d.zero_sales_percent - Decimal("14.2857142857")
    ) < Decimal("0.000000001")
    assert features.rolling_14d.total_units == 91
    assert features.rolling_30d.total_units == 435
    assert features.product_age_days == 100
    assert features.latest_base_price_change == Decimal("10.00")
    assert row.data_cutoff == CAPTURED and row.extract_cutoff == EXTRACT_CUTOFF
    assert row.quality.sufficient_history


def test_missing_days_stockout_and_known_zero(builder):
    history = task8_dataset(
        FEATURE_DATE - 30 * DAY,
        FEATURE_DATE - DAY,
        EXTRACT_CUTOFF,
        missing=(FEATURE_DATE - 2 * DAY,),
        stockouts=(FEATURE_DATE - DAY,),
        values={FEATURE_DATE - 7 * DAY: 0},
    )
    row = builder.build(
        snapshot(history=history), forecast_origin=ORIGIN, horizon_days=14
    )
    features = row.features
    assert features.sales_lag_1d is None and features.sales_lag_7d == 0
    assert features.rolling_7d.observed_days == 5
    assert (
        features.rolling_7d.total_units
        is features.rolling_7d.zero_sales_percent
        is None
    )
    assert features.previous_day_on_hand == 0 and features.previous_day_stockout is True
    assert (
        features.inventory_observed_days_30d == 29 and features.stockout_days_30d == 1
    )
    assert not row.quality.sufficient_history


def test_cold_start_and_timezone_boundary(builder):
    history = task8_dataset(
        FEATURE_DATE - DAY,
        FEATURE_DATE - DAY,
        EXTRACT_CUTOFF,
        missing=(FEATURE_DATE - DAY,),
    )
    # Task 8 emits an explicit missing product-day row for an owned product.
    history = history.model_copy(
        update={
            "rows": (
                DailyBusinessRow(
                    seller_id=SELLER,
                    product_id=PRODUCT,
                    business_date=FEATURE_DATE - DAY,
                    as_of_timestamp=EXTRACT_CUTOFF,
                    prediction_cutoff=_opening(FEATURE_DATE - DAY),
                    source_ids={},
                ),
            )
        }
    )
    new_catalog = CatalogSnapshot(
        seller_id=SELLER,
        product_id=PRODUCT,
        created_at=_opening(FEATURE_DATE) + timedelta(minutes=1),
        updated_at=_opening(FEATURE_DATE) + timedelta(minutes=1),
    )
    source = snapshot(history=history, catalog=new_catalog)
    utc_result = builder.build(source, forecast_origin=ORIGIN, horizon_days=7)
    foreign_tz = timezone(timedelta(hours=-8))
    result = builder.build(
        source, forecast_origin=ORIGIN.astimezone(foreign_tz), horizon_days=7
    )
    assert result.model_dump_json() == utc_result.model_dump_json()
    assert result.feature_date == FEATURE_DATE and ORIGIN.date() == FEATURE_DATE - DAY
    assert (
        result.features.product_age_days == 0 and result.features.sales_lag_1d is None
    )
    assert (
        result.features.previous_day_on_hand
        is result.features.previous_day_stockout
        is None
    )
    assert not result.quality.sufficient_history


def test_verified_holidays_weekends_month_end_and_future_revision(builder):
    source = snapshot()
    result = builder.build(source, forecast_origin=ORIGIN, horizon_days=30)
    calendar = result.features.target_calendar
    assert calendar[0].public_holiday is True  # Victory Day
    assert calendar[4].weekend is True  # Friday
    assert calendar[15].month_end is True  # 31 December is index 15.
    assert calendar[15].month == 12
    assert calendar[1].public_holiday is None
    assert result.calendar_versions == ("bd-mopa-2025-fixed-v1",)
    future = BangladeshHolidayCalendar(
        version="example-future-revision",
        source=AnyHttpUrl("https://example.com/revision"),
        published_at=ORIGIN,
        holidays={FEATURE_DATE + DAY: False},
    )
    revised = ForecastFeatureBuilder(
        authorized_seller_id=SELLER, calendars=(*BANGLADESH_CALENDARS, future)
    )
    assert revised.build(source, forecast_origin=ORIGIN, horizon_days=30) == result


def test_explicit_published_nonholiday_overrides_older_entry():
    revision = BangladeshHolidayCalendar(
        version="example-test-revision",
        source=AnyHttpUrl("https://example.com/revision"),
        published_at=ORIGIN - DAY,
        holidays={FEATURE_DATE + DAY: False},
    )
    builder = ForecastFeatureBuilder(
        authorized_seller_id=SELLER, calendars=(*BANGLADESH_CALENDARS, revision)
    )
    row = builder.build(snapshot(), forecast_origin=ORIGIN, horizon_days=7)
    assert row.features.target_calendar[0].public_holiday is False
    assert row.calendar_versions == ("example-test-revision",)


def test_competitor_cutoff_age_and_price_gap(builder):
    early = EXTRACT_CUTOFF - DAY
    baseline = (
        market("a", "70", early - DAY, early, 1),
        market("a", "80", early - timedelta(hours=1), early, 2),
        market("b", "100", early, early, 3),
    )
    expected = builder.build(
        snapshot(competitors=baseline), forecast_origin=ORIGIN, horizon_days=14
    )
    future = (
        market("a", "200", early, EXTRACT_CUTOFF, 4),
        market("new", "999", ORIGIN, ORIGIN + DAY, 5),
        market("stale", "5", ORIGIN - 8 * DAY, early, 6),
        market("invalid-time", "1", early + DAY, early, 7),
    )
    actual = builder.build(
        snapshot(competitors=baseline + future), forecast_origin=ORIGIN, horizon_days=14
    )
    assert actual == expected
    (market_features,) = actual.features.competitor_markets
    assert (
        market_features.median_price == Decimal(90)
        and market_features.listing_count == 2
    )
    assert actual.features.competitor_price_gap == Decimal(10)
    assert (
        market_features.newest_observation_age_seconds
        == (ORIGIN - early).total_seconds()
    )


@pytest.mark.parametrize("horizon", [7, 14, 30])
def test_training_inference_parity_and_schema(builder, horizon):
    source = ForecastSourceSnapshot.model_validate_json(snapshot().model_dump_json())
    inference = builder.build(source, forecast_origin=ORIGIN, horizon_days=horizon)
    start, end = FEATURE_DATE + DAY, FEATURE_DATE + horizon * DAY
    labels = task8_dataset(start, end, _opening(end + 4 * DAY))
    changed = task8_dataset(
        start,
        end,
        labels.as_of_timestamp,
        values={start: 99},
    )
    training = builder.build_training_example(
        source, forecast_origin=ORIGIN, horizon_days=horizon, outcomes=labels
    )
    future = builder.build_training_example(
        source, forecast_origin=ORIGIN, horizon_days=horizon, outcomes=changed
    )
    assert (
        training.feature_row.model_dump_json()
        == future.feature_row.model_dump_json()
        == inference.model_dump_json()
    )
    assert (
        training.target_net_units == horizon and future.target_net_units == horizon + 98
    )
    assert inference.target_start_date == start and inference.target_end_date == end
    assert len(inference.features.target_calendar) == horizon
    assert inference.version == "forecast-features-v1"
    assert inference.schema_sha256 == FEATURE_SCHEMA_SHA256
    assert (
        ForecastFeatureRow.model_validate_json(inference.model_dump_json()) == inference
    )
    with pytest.raises(ValidationError, match="schema_sha256"):
        ForecastFeatureRow.model_validate(
            inference.model_dump() | {"schema_sha256": "different"}
        )


def test_incomplete_target_and_backdated_extraction(builder):
    source = snapshot()
    labels = task8_dataset(
        FEATURE_DATE + DAY,
        FEATURE_DATE + 7 * DAY,
        _opening(FEATURE_DATE + 10 * DAY),
        stockouts=(FEATURE_DATE + DAY,),
    )
    result = builder.build_training_example(
        source, forecast_origin=ORIGIN, horizon_days=7, outcomes=labels
    )
    assert result.target_net_units is None and result.eligible_target_days == 6
    with pytest.raises(ValueError, match="captured before"):
        builder.build(
            snapshot(captured_at=ORIGIN + DAY), forecast_origin=ORIGIN, horizon_days=7
        )


def test_observed_zero_target_days_remain_eligible(builder):
    source = snapshot()
    labels = task8_dataset(
        FEATURE_DATE + DAY,
        FEATURE_DATE + 7 * DAY,
        _opening(FEATURE_DATE + 10 * DAY),
        values={FEATURE_DATE + offset * DAY: 0 for offset in range(1, 8)},
    )
    result = builder.build_training_example(
        source, forecast_origin=ORIGIN, horizon_days=7, outcomes=labels
    )
    assert result.target_net_units == 0
    assert result.eligible_target_days == 7


def test_invalid_rows_and_seller_and_product_isolation(builder):
    foreign = UUID(int=500)
    with pytest.raises(PermissionError):
        builder.build(
            snapshot(seller_id=foreign), forecast_origin=ORIGIN, horizon_days=7
        )
    foreign_observation = market(
        "foreign",
        "90",
        EXTRACT_CUTOFF - DAY,
        EXTRACT_CUTOFF - DAY,
        501,
        seller_id=foreign,
    )
    with pytest.raises(PermissionError):
        builder.build(
            snapshot(competitors=(foreign_observation,)),
            forecast_origin=ORIGIN,
            horizon_days=7,
        )
    original = snapshot().history
    wrong_scope = original.model_copy(
        update={
            "rows": (
                original.rows[0].model_copy(
                    update={
                        "seller_id": foreign,
                    }
                ),
            )
        }
    )
    with pytest.raises(PermissionError):
        builder.build(
            snapshot(history=wrong_scope), forecast_origin=ORIGIN, horizon_days=7
        )
    with pytest.raises(PermissionError):
        builder.build(
            snapshot(product_id=foreign), forecast_origin=ORIGIN, horizon_days=7
        )
    with pytest.raises(PermissionError):
        builder.build_training_example(
            snapshot(),
            forecast_origin=ORIGIN,
            horizon_days=7,
            outcomes=original.model_copy(update={"seller_id": foreign}),
        )
    duplicates = original.model_copy(
        update={"rows": (original.rows[0], original.rows[0])}
    )
    with pytest.raises(ValueError, match="duplicate"):
        builder.build(
            snapshot(history=duplicates), forecast_origin=ORIGIN, horizon_days=7
        )


def test_invalid_time_and_future_price_change(builder):
    source = snapshot()
    with pytest.raises(ValueError, match="aware"):
        builder.build(source, forecast_origin=datetime(2025, 12, 15), horizon_days=7)
    catalog = source.catalog.model_copy(update={"price_change_recorded_at": ORIGIN})
    row = builder.build(
        snapshot(catalog=catalog), forecast_origin=ORIGIN, horizon_days=7
    )
    assert row.features.known_base_price == Decimal("100.00")
    assert (
        row.features.latest_base_price_change
        is row.features.latest_price_change_at
        is None
    )
