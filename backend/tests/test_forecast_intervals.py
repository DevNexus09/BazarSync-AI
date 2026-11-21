from datetime import timedelta
from decimal import Decimal
import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.demand_regime import DemandRegime
from app.schemas.forecast_uncertainty import ForecastInterval, IntervalStatus
from app.schemas.ml_forecast import MLForecastResult, MLForecastStatus
from app.schemas.statistical_forecast import ForecastResult
from app.services.demand_regime_service import RegimeForecastService
from app.services.forecast_interval_replay import (
    regime_forecast_context,
    replay_regime_intervals,
)
from app.services.forecast_interval_service import (
    ForecastIntervalService,
    IntervalBacktestReport,
    IntervalSample,
    backtest_intervals,
)
from app.services.historical_dataset_service import DAY
from app.services.statistical_forecast_service import StatisticalForecastService
from test_statistical_forecast import DATE, SELLER, origin_case


@pytest.fixture
def forecaster():
    return RegimeForecastService(
        StatisticalForecastService(authorized_seller_id=SELLER)
    )


def cases(history, daily_outcomes, *, product=UUID(int=101), step=35):
    return [
        origin_case(
            history, actual=(units,) * 30, product=product, day=DATE + i * step * DAY
        )
        for i, units in enumerate(daily_outcomes)
    ]


def evaluate(forecaster, samples, *, split=DATE + 20 * 35 * DAY):
    return backtest_intervals(
        samples,
        seller_id=SELLER,
        forecast_context=regime_forecast_context(forecaster, None),
        test_start_date=split,
    )


@pytest.fixture
def replay(forecaster):
    archive = cases((10,) * 30, (7, 13) * 10 + (1, 10, 20))
    archive += cases(
        (0, 0, 0, 0, 0, 0, 4) * 6, (0,) * 21 + (2, 0), product=UUID(int=102)
    )
    archive += cases((0,) * 30, (0,) * 23, product=UUID(int=103))
    samples = list(replay_regime_intervals(archive, forecaster))
    report = evaluate(forecaster, samples)
    service = ForecastIntervalService(
        seller_id=SELLER,
        forecast_context=report.calibration.forecast_context,
        calibration=report.calibration,
    )
    return samples, report, service


def test_high_volatility_and_empirical_metrics(replay):
    samples, report, service = replay
    metrics = {(item.horizon_days, item.regime): item for item in report.metrics}
    regular = metrics[7, DemandRegime.REGULAR]
    assert regular.scored_rows == 3
    assert regular.average_width_units == 42
    assert abs(regular.empirical_coverage - Decimal(1) / 3) < Decimal("1e-27")
    assert (
        regular.empirical_coverage
        == regular.underprediction_frequency
        == regular.overprediction_frequency
    )
    assert metrics[30, DemandRegime.REGULAR].average_width_units == 180
    assert metrics[14, None].scored_rows == 9
    point = samples[20 * 3].forecast
    result = service.attach(point, regime=DemandRegime.REGULAR)
    interval = result.prediction_interval
    assert interval.status == IntervalStatus.EMPIRICAL_UNVALIDATED
    assert (interval.lower_bound, result.expected_units, interval.upper_bound) == (
        49,
        70,
        91,
    )
    assert interval.nominal_level == Decimal("0.90")
    assert interval.calibration_period.scored_windows == 20
    assert result.model_version == point.model_version
    assert ForecastResult.model_validate_json(result.model_dump_json()) == result


def test_intermittent_and_zero_history(replay):
    samples, report, service = replay
    first_test_origin = DATE + 20 * 35 * DAY
    for product_id in (102, 103):
        row = next(
            item
            for item in samples
            if item.forecast.product_id.int == product_id
            and item.forecast.target_start_date == first_test_origin + DAY
        )
        assert row.regime == DemandRegime.INTERMITTENT
        interval = service.attach(row.forecast, regime=row.regime).prediction_interval
        assert interval.lower_bound == 0
        assert interval.upper_bound == (8 if product_id == 102 else 1)
    intermittent = next(
        item
        for item in report.metrics
        if item.horizon_days == 7 and item.regime == DemandRegime.INTERMITTENT
    )
    assert intermittent.scored_rows == 6
    assert intermittent.underprediction_frequency > 0


def test_no_calibration_and_missing_interval_values(replay):
    samples, report, _ = replay
    point = samples[0].forecast
    assert point.prediction_interval is None
    assert "prediction_interval" not in point.model_dump()
    payload = point.model_dump() | {"prediction_interval": None}
    assert ForecastResult.model_validate(payload) == point
    service = ForecastIntervalService(
        seller_id=SELLER, forecast_context=report.calibration.forecast_context
    )
    result = service.attach(point, regime=DemandRegime.REGULAR)
    assert result.prediction_interval.status == IntervalStatus.UNCALIBRATED
    assert result.prediction_interval.lower_bound is None
    assert result.expected_units == point.expected_units
    with pytest.raises(ValidationError):
        ForecastInterval(status=IntervalStatus.EMPIRICAL_UNVALIDATED)


@pytest.mark.parametrize(
    "changes",
    [
        {"lower_bound": -1},
        {"upper_bound": "NaN"},
        {"upper_bound": "Infinity"},
        {"lower_bound": 92},
        {"lower_bound": 69.99, "upper_bound": 70},
        {"lower_bound": 71},
        {"upper_bound": 69},
    ],
)
def test_invalid_bounds_and_interval_ordering(replay, changes):
    samples, _, service = replay
    result = service.attach(samples[60].forecast, regime=DemandRegime.REGULAR)
    data = result.model_dump()
    data["prediction_interval"].update(changes)
    with pytest.raises(ValidationError):
        ForecastResult.model_validate(data)


def test_horizon_regime_and_context_mismatch(replay):
    samples, report, service = replay
    point = samples[60].forecast
    wrong = point.model_copy(update={"horizon_days": 14})
    with pytest.raises(ValueError, match="horizon"):
        service.attach(wrong, regime=DemandRegime.REGULAR)
    reduced = report.calibration.model_copy(
        update={
            "profiles": tuple(
                p for p in report.calibration.profiles if p.key.horizon_days == 14
            )
        }
    )
    reduced_service = ForecastIntervalService(
        seller_id=SELLER,
        forecast_context=reduced.forecast_context,
        calibration=reduced,
    )
    assert (
        reduced_service.attach(
            point, regime=DemandRegime.REGULAR
        ).prediction_interval.status
        == IntervalStatus.INSUFFICIENT_DATA
    )
    assert (
        service.attach(
            point, regime=DemandRegime.POTENTIALLY_DECLINING
        ).prediction_interval.status
        == IntervalStatus.INSUFFICIENT_DATA
    )
    changed = ForecastIntervalService(
        seller_id=SELLER, forecast_context="changed", calibration=reduced
    )
    assert (
        changed.attach(point, regime=DemandRegime.REGULAR).prediction_interval.reason
        == "FORECAST_CONTEXT_MISMATCH"
    )


def test_chronological_calibration_embargo_and_test_independence(forecaster, replay):
    samples, report, service = replay
    split = report.calibration.test_start_date
    changed = [
        row.model_copy(update={"actual_units": 999_999})
        if row.forecast.target_start_date > split
        else row
        for row in reversed(samples)
    ]
    rerun = evaluate(forecaster, changed)
    assert rerun.calibration == report.calibration
    assert rerun.metrics != report.metrics
    assert evaluate(forecaster, reversed(samples)) == report
    assert (
        service.attach(
            samples[0].forecast, regime=DemandRegime.REGULAR
        ).prediction_interval.reason
        == "CALIBRATION_NOT_AVAILABLE_AT_ORIGIN"
    )
    late = samples[0].model_copy(
        update={"outcome_extract_cutoff": samples[60].outcome_extract_cutoff}
    )
    crossing_archive = cases((10,) * 30, (10,))
    crossing = origin_case(
        (10,) * 30, day=split - 2 * DAY, product=crossing_archive[0].snapshot.product_id
    )
    crossed = list(replay_regime_intervals([crossing], forecaster))
    embargo = evaluate(forecaster, [late, *samples[1:], *crossed])
    assert embargo.embargoed_rows == 4
    assert not any(
        p.key.horizon_days == 7 and p.key.product_id == late.forecast.product_id
        for p in embargo.calibration.profiles
    )


def test_overlapping_windows_do_not_meet_support_threshold(forecaster):
    archive = cases((10,) * 30, (10,) * 57, step=1)
    report = evaluate(
        forecaster, replay_regime_intervals(archive, forecaster), split=DATE + 55 * DAY
    )
    assert report.calibration.profiles == ()
    assert report.overlapping_calibration_rows > 0
    assert all(
        item.empirical_coverage is None and item.intervals_issued == 0
        for item in report.metrics
    )


def test_missing_point_has_no_interval(forecaster):
    case = origin_case((None,) * 3, age=3)
    result = forecaster.forecast(
        case.snapshot, forecast_origin=case.forecast_origin, horizon_days=7
    )
    service = ForecastIntervalService(
        seller_id=SELLER, forecast_context=regime_forecast_context(forecaster, None)
    )
    point = service.attach(result.forecast, regime=result.evidence.regime)
    assert point.expected_units is None
    assert point.prediction_interval.status == IntervalStatus.INSUFFICIENT_DATA
    assert point.prediction_interval.reason == "POINT_FORECAST_UNAVAILABLE"


def test_scope_and_missing_actual(forecaster, replay):
    samples, report, service = replay
    missing = samples[60].model_copy(update={"actual_units": None})
    changed = evaluate(forecaster, [*samples[:60], missing, *samples[61:]])
    row = next(
        m
        for m in changed.metrics
        if m.horizon_days == 7 and m.regime == DemandRegime.REGULAR
    )
    assert (row.test_rows, row.intervals_issued, row.scored_rows) == (3, 3, 2)
    foreign = UUID(int=999)
    with pytest.raises(PermissionError):
        ForecastIntervalService(
            seller_id=foreign, forecast_context="test", calibration=report.calibration
        )
    with pytest.raises(PermissionError):
        service.attach(
            samples[60].forecast.model_copy(update={"seller_id": foreign}),
            regime=DemandRegime.REGULAR,
        )


def test_catboost_interval_binds_model_checksum(forecaster, replay):
    rows, _, _ = replay
    samples = []
    for row in rows[:63:3]:
        point = row.forecast
        assert isinstance(point, ForecastResult)
        ml = MLForecastResult(
            **point.model_dump(
                include={
                    "seller_id",
                    "product_id",
                    "forecast_origin",
                    "horizon_days",
                    "target_start_date",
                    "target_end_date",
                    "expected_units",
                    "feature_version",
                }
            ),
            status=MLForecastStatus.AVAILABLE,
            model_version="catboost-demand-v1",
            model_sha256="a" * 64,
            feature_schema_sha256="b" * 64,
        )
        samples.append(
            IntervalSample(
                forecast=ml,
                regime=row.regime,
                actual_units=row.actual_units,
                outcome_extract_cutoff=row.outcome_extract_cutoff,
            )
        )
    report = evaluate(forecaster, samples)
    service = ForecastIntervalService(
        seller_id=SELLER,
        forecast_context=report.calibration.forecast_context,
        calibration=report.calibration,
    )
    point = samples[-1].forecast
    assert (
        service.attach(point, regime=DemandRegime.REGULAR).prediction_interval.status
        == IntervalStatus.EMPIRICAL_UNVALIDATED
    )
    replaced = point.model_copy(update={"model_sha256": "c" * 64})
    assert (
        service.attach(replaced, regime=DemandRegime.REGULAR).prediction_interval.status
        == IntervalStatus.INSUFFICIENT_DATA
    )


def test_offline_cli_from_archived_cases(tmp_path, monkeypatch, capsys):
    from scripts.backtest_forecast_intervals import main

    entries = []
    archive = cases((1,) * 30, (1,) * 21)
    for i, case in enumerate(archive):
        snapshot, outcomes = f"s-{i}.json", f"o-{i}.json"
        (tmp_path / snapshot).write_text(case.snapshot.model_dump_json())
        (tmp_path / outcomes).write_text(case.outcomes.model_dump_json())
        entries.append(
            dict(
                forecast_origin=case.forecast_origin.isoformat(),
                snapshot=snapshot,
                outcomes=outcomes,
            )
        )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"cases": entries}))
    monkeypatch.setattr(
        "sys.argv",
        [
            "task13",
            "--seller-id",
            str(SELLER),
            "--manifest",
            str(path),
            "--test-start",
            str(DATE + timedelta(days=700)),
        ],
    )
    main()
    report = IntervalBacktestReport.model_validate_json(capsys.readouterr().out)
    assert len(report.calibration.profiles) == 3
    assert all(row.empirical_coverage == 1 for row in report.metrics)
