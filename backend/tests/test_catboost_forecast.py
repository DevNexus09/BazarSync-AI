from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.forecast_features import (
    FEATURE_SCHEMA_SHA256,
    CalendarFeatures,
    ForecastFeatureQuality,
    ForecastFeatureRow,
    ForecastFeatures,
    ForecastTrainingExample,
    SalesWindow,
)
from app.schemas.demand_regime import DemandRegime
from app.schemas.ml_forecast import (
    CatBoostTrainingConfig,
    EvaluationScope,
    MLForecastStatus,
    ModelSelectionStatus,
)
from app.schemas.statistical_forecast import ProductCohort

pytest.importorskip("catboost")

from app.services.catboost_forecast_service import (  # noqa: E402
    CatBoostForecastService,
    CatBoostTrainingService,
    TrainingSample,
    flatten_feature_row,
)
from scripts.verify_catboost_environment import verify  # noqa: E402

SELLER = UUID(int=501)
PRODUCT = UUID(int=502)
UTC = timezone.utc


def _calendar(day: date) -> CalendarFeatures:
    return CalendarFeatures(
        day_of_week=day.weekday(),
        month=day.month,
        weekend=day.weekday() in (4, 5),
        month_end=False,
        public_holiday=None,
    )


def _row(origin_day: date, horizon: int, signal: int, *, sufficient=True):
    origin = datetime.combine(origin_day, time(hour=12), UTC)
    target_start = origin_day + timedelta(days=1)
    empty = SalesWindow(
        days=7,
        observed_days=7,
        total_units=signal * 7,
        population_stddev=Decimal("0"),
        zero_sales_percent=Decimal("0"),
    )
    features = ForecastFeatures(
        sales_lag_1d=signal,
        sales_lag_7d=signal,
        sales_lag_14d=signal,
        sales_lag_28d=signal,
        rolling_7d=empty,
        rolling_14d=empty.model_copy(
            update={"days": 14, "observed_days": 14, "total_units": signal * 14}
        ),
        rolling_30d=empty.model_copy(
            update={"days": 30, "observed_days": 30, "total_units": signal * 30}
        ),
        category="electronics" if signal % 2 else "home",
        brand=None,
        product_age_days=120,
        known_base_price=None,
        price_currency=None,
        latest_base_price_change=None,
        latest_price_change_at=None,
        feature_calendar=_calendar(origin_day),
        target_calendar=tuple(
            _calendar(target_start + timedelta(days=i)) for i in range(horizon)
        ),
        competitor_markets=(),
        competitor_price_gap=None,
        previous_day_on_hand=None,
        previous_day_stockout=False,
        inventory_observed_days_30d=0,
        stockout_days_30d=0,
        previous_day_promotion=None,
        previous_day_discount=None,
    )
    return ForecastFeatureRow(
        schema_sha256=FEATURE_SCHEMA_SHA256,
        historical_dataset_version="daily-business-v1",
        source_snapshot_version="forecast-source-v1",
        seller_id=SELLER,
        product_id=PRODUCT,
        feature_date=origin_day,
        forecast_origin=origin,
        data_cutoff=origin - timedelta(minutes=2),
        extract_cutoff=origin - timedelta(minutes=3),
        horizon_days=horizon,
        target_start_date=target_start,
        target_end_date=origin_day + timedelta(days=horizon),
        calendar_versions=(),
        features=features,
        quality=ForecastFeatureQuality(
            sufficient_history=sufficient,
            usable_sales_days_30d=30 if sufficient else 2,
            flags=() if sufficient else ("INSUFFICIENT_HISTORY",),
        ),
    )


def _samples(*, test_multiplier=1):
    samples = []
    for horizon in (7, 14, 30):
        for index in range(12):
            day = date(2024, 1, 1) + timedelta(days=35 * index)
            signal = index + 1
            target = signal * horizon
            if index >= 10:
                target *= test_multiplier
            row = _row(day, horizon, signal)
            samples.append(
                TrainingSample(
                    example=ForecastTrainingExample(
                        feature_row=row,
                        target_net_units=target,
                        eligible_target_days=horizon,
                        outcome_extract_cutoff=row.forecast_origin
                        + timedelta(days=horizon + 2),
                    ),
                    cohort=ProductCohort.HIGH_VOLUME
                    if signal > 5
                    else ProductCohort.LOW_VOLUME,
                    category=row.features.category or "unknown",
                    mase_scale=Decimal(horizon),
                    baseline_forecasts={
                        "naive": Decimal(0),
                        "moving_average": Decimal(0),
                    },
                    demand_regime=DemandRegime.REGULAR,
                )
            )
    return samples


def _config():
    return CatBoostTrainingConfig(
        iterations=20,
        early_stopping_rounds=5,
        rolling_folds=1,
        validation_origins=2,
        test_origins=2,
        minimum_training_rows=4,
        minimum_test_rows=2,
        thread_count=1,
    )


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    output = tmp_path_factory.mktemp("catboost-model")
    report = CatBoostTrainingService(seller_id=SELLER, config=_config()).train(
        _samples(),
        output_dir=output,
        scope=EvaluationScope.SYNTHETIC,
        generated_at=datetime(2026, 11, 16, tzinfo=UTC),
    )
    return output, report


def test_feature_schema_and_invalid_shape_validation():
    row = _row(date(2025, 1, 1), 7, 3)
    assert flatten_feature_row(row)["category"] == "electronics"
    with pytest.raises(ValidationError, match="schema_sha256"):
        ForecastFeatureRow.model_validate(row.model_dump() | {"schema_sha256": "bad"})
    invalid = row.model_copy(
        update={"features": row.features.model_copy(update={"target_calendar": ()})}
    )
    with pytest.raises(ValueError, match="calendar length"):
        flatten_feature_row(invalid)


def test_deterministic_training_and_chronological_holdout(tmp_path):
    kwargs = dict(
        scope=EvaluationScope.SYNTHETIC, generated_at=datetime(2026, 11, 16, tzinfo=UTC)
    )
    first = CatBoostTrainingService(seller_id=SELLER, config=_config()).train(
        _samples(), output_dir=tmp_path / "first", **kwargs
    )
    changed = CatBoostTrainingService(seller_id=SELLER, config=_config()).train(
        _samples(test_multiplier=20), output_dir=tmp_path / "changed", **kwargs
    )
    assert [item.candidate_results for item in first.results] == [
        item.candidate_results for item in changed.results
    ]
    assert [item.selected_candidate for item in first.results] == [
        item.selected_candidate for item in changed.results
    ]
    fixed_row = _row(date(2026, 1, 1), 7, 13)
    first_forecast = CatBoostForecastService(
        metadata_path=tmp_path / "first/catboost-horizon-7.metadata.json",
        authorized_seller_id=SELLER,
    ).forecast(fixed_row)
    changed_forecast = CatBoostForecastService(
        metadata_path=tmp_path / "changed/catboost-horizon-7.metadata.json",
        authorized_seller_id=SELLER,
    ).forecast(fixed_row)
    assert first_forecast.expected_units == changed_forecast.expected_units
    for result in first.results:
        assert result.test_start_date == date(2024, 1, 1) + timedelta(days=35 * 10)
        assert result.development_rows == 10
        assert result.embargoed_rows == 0
        assert result.test_rows == 2


def test_serialization_inference_shape_missing_data_and_cold_start(
    trained, monkeypatch
):
    output, report = trained
    result = report.results[0]
    service = CatBoostForecastService(
        metadata_path=output / "catboost-horizon-7.metadata.json",
        authorized_seller_id=SELLER,
    )
    row = _row(date(2026, 1, 1), 7, 13)
    forecast = service.forecast(row)
    assert forecast.status == MLForecastStatus.AVAILABLE
    assert forecast.expected_units is not None and forecast.expected_units >= 0
    assert forecast.model_sha256 == result.model_sha256
    with pytest.raises(ValueError, match="horizon"):
        service.forecast(_row(date(2026, 1, 1), 14, 13))
    cold = service.forecast(_row(date(2026, 1, 1), 7, 1, sufficient=False))
    assert cold.status == MLForecastStatus.INSUFFICIENT_DATA
    assert cold.expected_units is None and cold.reason == "INSUFFICIENT_FEATURE_HISTORY"
    monkeypatch.setattr(
        service.model, "predict", lambda _pool, **_kwargs: [float("nan")]
    )
    with pytest.raises(RuntimeError, match="invalid forecast"):
        service.forecast(row)


def test_holdout_accuracy_comparison_and_category_cohort_metrics(trained):
    _, report = trained
    assert report.live_recommendations_enabled is False
    assert report.production_selection_allowed is False
    for result in report.results:
        assert result.status == ModelSelectionStatus.SELECTED
        overall = [
            m
            for m in result.metrics
            if m.category == "all" and m.cohort == ProductCohort.ALL
        ]
        catboost = next(m for m in overall if m.model_name == "catboost")
        baseline = next(m for m in overall if m.model_name == "naive")
        assert catboost.mae is not None and baseline.mae is not None
        assert catboost.mae < baseline.mae
        assert any(m.category != "all" for m in result.metrics)
        assert any(m.cohort != ProductCohort.ALL for m in result.metrics)


def test_insufficient_dataset_does_not_train(tmp_path):
    report = CatBoostTrainingService(seller_id=SELLER, config=_config()).train(
        _samples()[:3], output_dir=tmp_path, scope=EvaluationScope.SYNTHETIC
    )
    assert all(
        item.status == ModelSelectionStatus.INSUFFICIENT_DATA for item in report.results
    )
    assert not list(Path(tmp_path).glob("*.cbm"))


def test_embargo_excludes_overlap_and_late_labels():
    service = CatBoostTrainingService(seller_id=SELLER, config=_config())
    start = date(2025, 1, 1)
    sample = _samples()[0]
    cases = []
    for offset in range(35):
        row = _row(start + timedelta(days=offset), 7, offset + 1)
        example = sample.example.model_copy(
            update={
                "feature_row": row,
                "outcome_extract_cutoff": row.forecast_origin
                + timedelta(days=9 if offset != 20 else 20),
                "target_net_units": None if offset == 34 else 10,
            }
        )
        cases.append(replace(sample, example=example))
    development, embargo, test, test_start = service._split(service._validate(cases))
    assert test_start == start + timedelta(days=33)
    assert len(test) == 1
    assert cases[20] in embargo
    assert cases[26] in embargo
    assert cases[24] in embargo
    assert cases[23] in development
    training, validation = service._folds(development)[0]
    origin = validation[0].example.feature_row.forecast_origin
    assert all(item.example.outcome_extract_cutoff < origin for item in training)
    assert all(
        item.example.feature_row.target_end_date
        < validation[0].example.feature_row.feature_date
        for item in training
    )


def test_deployment_environment_dependency_smoke():
    result = verify()
    assert result["status"] == "ok"
    assert result["dependencies"]["catboost"] == "1.2.10"
    assert result["task_type"] == "CPU"


def write_archived_fixture(tmp_path):
    from test_statistical_forecast import SELLER as archive_seller, origin_case

    cases = []
    for index in range(12):
        level = 1 + index % 5
        for product, category in ((UUID(int=901), "home"), (UUID(int=902), "books")):
            pattern = (
                (0, 0, level * 2) if category == "books" else (level * 3, level * 4)
            )
            case = origin_case(
                tuple(pattern[i % len(pattern)] for i in range(65)),
                actual=tuple(pattern[(i + 66) % len(pattern)] for i in range(30)),
                product=product,
                day=date(2024, 1, 1) + timedelta(days=35 * index),
            )
            snapshot = case.snapshot.model_copy(
                update={
                    "catalog": case.snapshot.catalog.model_copy(
                        update={"category": category}
                    )
                }
            )
            prefix = f"{index}-{product.int}"
            snapshot_file = f"{prefix}-snapshot.json"
            outcomes_file = f"{prefix}-outcomes.json"
            (tmp_path / snapshot_file).write_text(
                snapshot.model_dump_json(), encoding="utf-8"
            )
            (tmp_path / outcomes_file).write_text(
                case.outcomes.model_dump_json(), encoding="utf-8"
            )
            cases.append(
                dict(
                    forecast_origin=case.forecast_origin.isoformat(),
                    snapshot=snapshot_file,
                    outcomes=outcomes_file,
                )
            )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "scope": "synthetic",
                "cases": cases,
                "config": _config().model_dump(mode="json"),
            }
        ),
        encoding="utf-8",
    )
    return archive_seller, manifest


def test_offline_training_cli_smoke(tmp_path, monkeypatch, capsys):
    from hashlib import sha256

    from scripts.train_catboost_forecasts import main

    seller, manifest = write_archived_fixture(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "train-catboost",
            "--seller-id",
            str(seller),
            "--manifest",
            str(manifest),
            "--output-dir",
            str(tmp_path / "models"),
        ],
    )
    main()
    report = json.loads(capsys.readouterr().out)
    assert report["scope"] == "synthetic"
    assert report["live_recommendations_enabled"] is False
    assert all(result["model_file"] for result in report["results"])
    assert all(
        any(metric["model_name"] == "auto" for metric in result["metrics"])
        for result in report["results"]
    )
    assert (tmp_path / "models/evaluation.json").exists()
    lineage = (tmp_path / "models/lineage.json").read_bytes()
    assert sha256(lineage).hexdigest() == report["lineage_sha256"]
    entries = json.loads(lineage)["cases"]
    assert len(entries) == 24
    assert (
        entries[0]["snapshot_sha256"]
        == sha256((tmp_path / "0-901-snapshot.json").read_bytes()).hexdigest()
    )
    for row in report["results"]:
        assert row["deployment_ineligible_rows"] == 12
        assert row["test_rows"] == 2
        saved = json.loads(
            (
                tmp_path
                / f"models/catboost-horizon-{row['horizon_days']}.metadata.json"
            ).read_bytes()
        )
        assert saved["lineage_sha256"] == report["lineage_sha256"]
        assert any(
            metric["model_name"] == "regime_fallback" for metric in row["metrics"]
        )


def test_empty_archive_origin_still_reserves_holdout_date(tmp_path):
    from scripts.train_catboost_forecasts import (
        TrainingManifest,
        _samples as archived_samples,
    )

    seller, path = write_archived_fixture(tmp_path)
    source = tmp_path / "11-901-snapshot.json"
    payload = json.loads(source.read_bytes())
    payload["history"]["rows"] = []
    source.write_text(json.dumps(payload))
    manifest = TrainingManifest.model_validate_json(path.read_bytes())
    samples = list(archived_samples(manifest, tmp_path, seller))
    service = CatBoostTrainingService(seller_id=seller, config=manifest.config)
    horizon = [row for row in samples if row.example.feature_row.horizon_days == 30]
    _, _, test, boundary = service._split(horizon)
    assert boundary == date(2024, 1, 1) + timedelta(days=35 * 10)
    assert len(test) == 1
    latest_date = date(2024, 1, 1) + timedelta(days=35 * 11)
    assert any(
        row.example.feature_row.feature_date == latest_date
        and row.demand_regime == DemandRegime.INSUFFICIENT_HISTORY
        for row in horizon
    )
