from datetime import date, timedelta
from decimal import Decimal
import json
from uuid import UUID

import pytest

from app.schemas.forecast_features import CatalogSnapshot, ForecastSourceSnapshot
from app.schemas.statistical_forecast import (
    BacktestReport,
    BaselineConfig,
    BaselineModel,
    DataSufficiencyStatus,
    EvidenceStatus,
    ProductCohort,
)
from app.services.forecast_backtesting_service import (
    ForecastBacktestingService,
    RollingOriginCase,
)
from app.services.historical_dataset_service import (
    DAY,
    DailyBusinessRow,
    HistoricalDataset,
    HistoricalDatasetQuality,
    _opening,
)
from app.services.statistical_forecast_service import (
    NATIVE_MODELS,
    STATSFORECAST_MODELS,
    StatisticalForecastService,
)

SELLER = UUID(int=1)
PRODUCT = UUID(int=2)
DATE = date(2025, 12, 15)


def dataset(values, start, cutoff, *, product=PRODUCT, stockouts=()):
    rows = tuple(
        DailyBusinessRow(
            seller_id=SELLER,
            product_id=product,
            business_date=day,
            prediction_cutoff=_opening(day),
            as_of_timestamp=cutoff,
            observed_units_sold=units,
            sales_coverage_complete=True,
            forecast_label_eligible=offset not in stockouts,
            stockout_indicator=offset in stockouts,
            on_hand_stock=0 if offset in stockouts else 50,
            source_ids={},
        )
        for offset, units in enumerate(values)
        if units is not None
        for day in [start + offset * DAY]
    )
    return HistoricalDataset(
        seller_id=SELLER,
        start_date=start,
        end_date=start + (len(values) - 1) * DAY,
        as_of_timestamp=cutoff,
        rows=rows,
        quality=HistoricalDatasetQuality(
            row_count=len(rows),
            product_count=1,
            products_with_observed_sales=1,
            history_days=len(values),
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


def origin_case(
    history, *, actual=(2,) * 30, day=DATE, product=PRODUCT, age=100, stockouts=()
):
    origin = _opening(day) + timedelta(hours=4)
    cutoff = origin - timedelta(minutes=2)
    return RollingOriginCase(
        forecast_origin=origin,
        snapshot=ForecastSourceSnapshot(
            captured_at=origin - timedelta(minutes=1),
            seller_id=SELLER,
            product_id=product,
            history=dataset(
                history,
                day - len(history) * DAY,
                cutoff,
                product=product,
                stockouts=stockouts,
            ),
            catalog=CatalogSnapshot(
                seller_id=SELLER,
                product_id=product,
                created_at=_opening(day - age * DAY),
                updated_at=cutoff - timedelta(hours=1),
            ),
        ),
        outcomes=dataset(
            actual, day + DAY, _opening(day + (len(actual) + 3) * DAY), product=product
        ),
    )


@pytest.fixture
def service():
    return StatisticalForecastService(authorized_seller_id=SELLER)


def forecast(service, case, horizon=7, model=BaselineModel.AUTO):
    return service.forecast(
        case.snapshot,
        forecast_origin=case.forecast_origin,
        horizon_days=horizon,
        model=model,
        generated_at=case.forecast_origin,
    )


@pytest.mark.parametrize("horizon", [7, 14, 30])
def test_constant_demand_native_baselines(service, horizon):
    case = origin_case((4,) * 30)
    for model in (
        BaselineModel.NAIVE,
        BaselineModel.MOVING_AVERAGE,
        BaselineModel.EXPONENTIAL_SMOOTHING,
    ):
        result = forecast(service, case, horizon, model)
        assert result.expected_units == Decimal(4 * horizon)
        assert result.evidence_status == EvidenceStatus.ELIGIBLE_OBSERVED_SALES
        assert result.target_start_date == DATE + DAY
        assert result.target_end_date == DATE + horizon * DAY
        assert result.generated_at == case.forecast_origin
    assert (
        forecast(service, case, horizon, BaselineModel.SEASONAL_NAIVE).expected_units
        is None
    )


def test_weekly_seasonality_and_skipped_feature_day(service):
    case = origin_case(tuple(range(1, 8)) * 4)
    result = forecast(service, case, 30)
    assert result.model_name == BaselineModel.SEASONAL_NAIVE
    assert result.expected_units == 4 * 28 + 2 + 3
    assert result.model_dump_json() == forecast(service, case, 30).model_dump_json()


def test_insufficient_history_and_configurable_fallback(service):
    case = origin_case((1, 2, 3), age=4)
    result = forecast(service, case)
    assert result.expected_units is result.model_name is None
    assert result.data_sufficiency_status == DataSufficiencyStatus.INSUFFICIENT
    assert result.evidence_status == EvidenceStatus.UNAVAILABLE
    assert result.fallback_reason == "MINIMUM_CONTIGUOUS_HISTORY"
    relaxed = StatisticalForecastService(
        authorized_seller_id=SELLER,
        config=BaselineConfig(minimum_history_days=3),
    )
    fallback = forecast(relaxed, case)
    assert fallback.expected_units == 21
    assert fallback.model_name == BaselineModel.NAIVE
    assert fallback.fallback_reason == "MOVING_AVERAGE_WINDOW_UNAVAILABLE"


def test_all_zero_forecast_and_metrics(service):
    case = origin_case((0,) * 65, actual=(0,) * 30)
    result = forecast(service, case)
    assert result.expected_units == 0
    report = ForecastBacktestingService(service).evaluate(
        [case], models=(BaselineModel.AUTO,)
    )
    for metrics in report.metrics:
        assert metrics.mae == metrics.bias_units == 0
        assert metrics.wape_percent is metrics.mase is None
        assert metrics.cohort in (ProductCohort.ALL, ProductCohort.ZERO_DEMAND)


def test_missing_and_stockout_days_break_contiguous_history(service):
    missing = origin_case((3,) * 30 + (None,) + (2,) * 5)
    censored = origin_case((3,) * 35 + (0,), stockouts=(35,))
    assert forecast(service, missing).contiguous_history_days == 5
    assert forecast(service, missing).expected_units is None
    assert forecast(service, censored).contiguous_history_days == 0
    assert forecast(service, censored).expected_units is None
    observed_zero = origin_case((3,) * 35 + (0,))
    assert (
        forecast(service, observed_zero, model=BaselineModel.NAIVE).expected_units == 0
    )


def test_invalid_and_negative_inputs_fail_closed(service):
    case = origin_case((3,) * 20 + (-1,))
    with pytest.raises(ValueError, match="nonnegative"):
        forecast(service, case)
    case = origin_case((3,) * 20)
    source = case.snapshot.history
    rows = (
        *source.rows[:-1],
        source.rows[-1].model_copy(update={"sales_coverage_complete": False}),
    )
    malformed = case.snapshot.model_copy(
        update={"history": source.model_copy(update={"rows": rows})}
    )
    with pytest.raises(ValueError, match="eligibility"):
        service.forecast(
            malformed, forecast_origin=case.forecast_origin, horizon_days=7
        )


def test_intermittent_native_and_optional_behavior(service):
    case = origin_case((0, 0, 0, 5, 0) * 8)
    auto = forecast(service, case)
    assert auto.expected_units >= 0
    assert (
        forecast(
            service, case, model=BaselineModel.EXPONENTIAL_SMOOTHING
        ).expected_units
        is None
    )
    disabled = forecast(service, case, model=BaselineModel.TSB)
    assert disabled.data_sufficiency_status == DataSufficiencyStatus.MODEL_UNAVAILABLE
    assert disabled.fallback_reason == "STATSFORECAST_DISABLED"


def test_statsforecast_intermittent_benchmarks():
    pytest.importorskip("statsforecast")
    forecaster = StatisticalForecastService(
        authorized_seller_id=SELLER, enable_statsforecast=True
    )
    case = origin_case((0, 0, 0, 5, 0) * 8)
    report = ForecastBacktestingService(forecaster).evaluate([case])
    assert report.statsforecast_version == "2.1.1"
    assert report.statsforecast_dependencies["numpy"]
    intermittent = [
        fold
        for fold in report.folds
        if fold.forecast.requested_model in STATSFORECAST_MODELS
    ]
    assert len(intermittent) == 15
    for fold in intermittent:
        result = fold.forecast
        assert result.expected_units is not None and result.expected_units >= 0
        assert (
            forecast(forecaster, case, result.horizon_days, result.requested_model)
            == result
        )


def test_scoring_and_rolling_origin_replay(service):
    first = origin_case((1,) * 7 + (3,) * 7)
    second = origin_case((8,) * 30, day=DATE + 7 * DAY, actual=(2,) * 29 + (None,))
    evaluator = ForecastBacktestingService(service)
    settings = {"models": (BaselineModel.NAIVE,)}
    report = evaluator.evaluate([second, first], **settings)
    assert (
        report.model_dump_json()
        == evaluator.evaluate([first, second], **settings).model_dump_json()
    )
    assert len(report.folds) == 6
    assert report.folds[0].forecast.expected_units == 21
    assert report.folds[0].observed_target_units == 14
    assert report.folds[0].mase_scale == 14
    low = next(
        metric
        for metric in report.metrics
        if metric.horizon_days == 7 and metric.cohort == ProductCohort.LOW_VOLUME
    )
    assert (low.mae, low.wape_percent, low.mase, low.bias_units) == (
        7,
        50,
        Decimal("0.5"),
        7,
    )
    long = next(
        metric
        for metric in report.metrics
        if metric.horizon_days == 30 and metric.cohort == ProductCohort.ALL
    )
    assert long.forecasted_folds == 2 and long.scored_folds == 1
    assert report.folds[-1].observed_target_units is None


def test_repeated_dhaka_date_and_conflicting_mature_outcomes_are_rejected(service):
    first = origin_case((2,) * 30)
    duplicate = RollingOriginCase(
        first.forecast_origin + timedelta(hours=1),
        first.snapshot,
        first.outcomes,
    )
    evaluator = ForecastBacktestingService(service)
    with pytest.raises(ValueError, match="origin business date"):
        evaluator.evaluate([first, duplicate])
    newer = origin_case((2,) * 30, day=DATE + 7 * DAY, actual=(3,) * 30)
    with pytest.raises(ValueError, match="Conflicting observed outcomes"):
        evaluator.evaluate([first, newer])


def test_30_day_mase_scale_uses_disjoint_in_sample_blocks(service):
    case = origin_case((1,) * 30 + (3,) * 30)
    report = ForecastBacktestingService(service).evaluate(
        [case],
        models=(BaselineModel.NAIVE,),
        horizons=(30,),
    )
    (fold,) = report.folds
    assert fold.mase_scale == 60
    assert fold.observed_target_units == 60
    assert fold.forecast.expected_units == 90
    assert report.metrics[0].mase == Decimal("0.5")


def test_future_changes_cannot_change_historical_forecasts_or_cohorts(service):
    first = origin_case((1, 2, 3) * 10)
    changed = origin_case((1, 2, 3) * 10, actual=(50,) * 30)
    evaluator = ForecastBacktestingService(service)
    original = evaluator.evaluate([first])
    revised = evaluator.evaluate([changed])
    assert [fold.forecast for fold in original.folds] == [
        fold.forecast for fold in revised.folds
    ]
    assert [fold.cohort for fold in original.folds] == [
        fold.cohort for fold in revised.folds
    ]
    assert (
        original.folds[0].observed_target_units
        != revised.folds[0].observed_target_units
    )
    future = first.snapshot.model_copy(update={"captured_at": first.forecast_origin})
    with pytest.raises(ValueError, match="captured before"):
        service.forecast(future, forecast_origin=first.forecast_origin, horizon_days=7)


def test_cohort_reasons_and_cross_seller_isolation(service):
    cases = [
        origin_case((1,) * 14, product=UUID(int=3)),
        origin_case((6,) * 14, product=UUID(int=4)),
        origin_case((0, 0, 7) * 10, product=UUID(int=5)),
        origin_case((1, 2), age=3, product=UUID(int=6)),
    ]
    evaluator = ForecastBacktestingService(service)
    report = evaluator.evaluate(cases, models=(BaselineModel.NAIVE,), horizons=(7,))
    assert {fold.cohort for fold in report.folds} == {
        ProductCohort.LOW_VOLUME,
        ProductCohort.HIGH_VOLUME,
        ProductCohort.INTERMITTENT,
        ProductCohort.NEW,
    }
    with pytest.raises(ValueError, match="Duplicate"):
        evaluator.evaluate([cases[0], cases[0]])
    foreign = cases[0].outcomes.model_copy(update={"seller_id": UUID(int=9)})
    with pytest.raises(PermissionError):
        evaluator.evaluate(
            [RollingOriginCase(cases[0].forecast_origin, cases[0].snapshot, foreign)]
        )


def test_offline_cli_smoke(tmp_path, monkeypatch, capsys):
    from scripts.backtest_statistical_forecasts import main

    case = origin_case((4,) * 30)
    manifest = tmp_path / "manifest.json"
    (tmp_path / "history.json").write_text(case.snapshot.model_dump_json())
    (tmp_path / "outcomes.json").write_text(case.outcomes.model_dump_json())
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "forecast_origin": case.forecast_origin.isoformat(),
                        "snapshot": "history.json",
                        "outcomes": "outcomes.json",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(
        "sys.argv",
        ["backtest", "--seller-id", str(SELLER), "--manifest", str(manifest)],
    )
    main()
    report = BacktestReport.model_validate_json(capsys.readouterr().out)
    assert len(report.folds) == 3 * (1 + len(NATIVE_MODELS))


def test_phase3_fixture_rolling_origin_replay():
    pytest.importorskip("statsforecast")
    cases = []
    patterns = {
        "high": (1, 4, 10, 13, 10, 7, 4),
        "low": (1, 1, 2, 1, 3),
        "intermittent": (0, 0, 0, 5, 0),
        "zero": (0,),
        "new": (1, 1, 2),
        "gap": (1,),
    }
    for number, (name, sequence) in enumerate(patterns.items(), start=1):
        for offset in (0, 7):
            days = 4 + offset if name == "new" else 75
            history = tuple(
                sequence[i % len(sequence)] for i in range(offset - days, offset)
            )
            if name == "gap":
                history = (*history[:-1], None)
            actual = tuple(
                sequence[i % len(sequence)] for i in range(offset + 1, offset + 31)
            )
            cases.append(
                origin_case(
                    history,
                    actual=actual,
                    day=DATE + offset * DAY,
                    product=UUID(int=100 + number),
                    age=days if name == "new" else days + 100,
                )
            )
    service = StatisticalForecastService(
        authorized_seller_id=SELLER, enable_statsforecast=True
    )
    evaluator = ForecastBacktestingService(service)
    report = evaluator.evaluate(cases)
    assert (
        report.model_dump_json()
        == evaluator.evaluate(reversed(cases)).model_dump_json()
    )
    assert len(report.folds) == 360
    auto = [
        metric
        for metric in report.metrics
        if metric.model == BaselineModel.AUTO and metric.cohort == ProductCohort.ALL
    ]
    assert [row.horizon_days for row in auto] == [7, 14, 30]
    assert all(row.scored_folds == row.forecasted_folds == 8 for row in auto)
    assert [round(row.mae, 4) for row in auto] == [
        Decimal("1.6250"),
        Decimal("1.6250"),
        Decimal("3.8036"),
    ]
