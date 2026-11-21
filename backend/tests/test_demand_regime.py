from dataclasses import replace
from decimal import Decimal
import json
from uuid import UUID

import pytest

from app.schemas.demand_regime import (
    DemandRegime,
    DemandRegimeEvidence,
    RegimeSelectionPolicy,
)
from app.schemas.statistical_forecast import (
    BaselineModel,
    DataSufficiencyStatus,
    ForecastResult,
)
from app.services.demand_regime_service import RegimeForecastService
from app.services.historical_dataset_service import DAY
from app.services.statistical_forecast_service import StatisticalForecastService
from test_statistical_forecast import DATE, SELLER, origin_case


@pytest.fixture
def service():
    return RegimeForecastService(
        StatisticalForecastService(authorized_seller_id=SELLER)
    )


def forecast(service, case, *, policy=None, horizon=7):
    return service.forecast(
        case.snapshot,
        forecast_origin=case.forecast_origin,
        horizon_days=horizon,
        policy=policy,
        generated_at=case.forecast_origin,
    )


def test_all_zero_verified_and_short_zero_history(service):
    estimate = forecast(service, origin_case((0,) * 30))
    assert estimate.evidence.regime == DemandRegime.INTERMITTENT
    assert estimate.evidence.population_variance == 0
    assert estimate.evidence.average_demand_interval_days is None
    assert estimate.forecast.expected_units == 0
    assert estimate.selection_reason == "OBSERVED_ZERO_HISTORY"
    assert forecast(service, origin_case((0,) * 21)).forecast.expected_units is None
    assert (
        ForecastResult.model_validate_json(estimate.forecast.model_dump_json())
        == estimate.forecast
    )


def test_single_sale_keeps_rate_below_one_unit_per_day(service):
    estimate = forecast(service, origin_case((0,) * 14 + (3,) + (0,) * 15), horizon=30)
    assert estimate.evidence.regime == DemandRegime.INTERMITTENT
    assert estimate.evidence.nonzero_days == 1
    assert estimate.evidence.average_demand_interval_days is None
    assert estimate.evidence.population_variance == Decimal("0.29")
    assert estimate.forecast.model_name == "historical_mean"
    assert estimate.forecast.expected_units == 3
    short = forecast(service, origin_case((0,) * 19 + (3,)))
    assert short.forecast.expected_units is None
    assert short.selection_reason == "SHORT_SINGLE_EVENT_HISTORY"


def test_frequent_sales(service):
    estimate = forecast(service, origin_case((2, 4) * 20))
    assert estimate.evidence.regime == DemandRegime.REGULAR
    assert estimate.evidence.nonzero_frequency == 1
    assert estimate.evidence.average_demand_interval_days == 1
    assert estimate.evidence.population_variance == 1
    assert estimate.forecast.expected_units == 21


def test_new_product_without_any_rows(service):
    result = forecast(service, origin_case((None,) * 3, age=3))
    assert result.evidence.regime == DemandRegime.INSUFFICIENT_HISTORY
    assert result.evidence.product_age_days == 3 and result.evidence.reliable_days == 0
    assert result.forecast.data_sufficiency_status == DataSufficiencyStatus.INSUFFICIENT
    assert result.forecast.expected_units is result.forecast.model_name is None


def test_sustained_decline_and_ordinary_intermittency(service):
    regular = (8,) * 28
    recent = (2,) * 28
    result = forecast(service, origin_case(regular + recent))
    assert result.evidence.regime == DemandRegime.POTENTIALLY_DECLINING
    assert (result.evidence.previous_28_units, result.evidence.recent_28_units) == (
        224,
        56,
    )
    assert result.forecast.expected_units == 14
    assert (
        forecast(service, origin_case(regular + (8,) * 14 + (0,) * 14)).evidence.regime
        != DemandRegime.POTENTIALLY_DECLINING
    )
    irregular = (0, 0, 3, 0, 5, 0, 0) * 8
    assert (
        forecast(service, origin_case(irregular)).evidence.regime
        == DemandRegime.INTERMITTENT
    )


@pytest.mark.parametrize("kind", ["missing", "censored", "coverage"])
def test_unreliable_days_are_never_zero(service, kind):
    case = origin_case(
        (2,) * 28 + (0,) * 28, stockouts=(55,) if kind == "censored" else ()
    )
    history = case.snapshot.history
    if kind in {"missing", "coverage"}:
        rows = history.rows[:-1]
        if kind == "coverage":
            rows += (
                history.rows[-1].model_copy(
                    update={
                        "sales_coverage_complete": False,
                        "forecast_label_eligible": False,
                    }
                ),
            )
        case = replace(
            case,
            snapshot=case.snapshot.model_copy(
                update={"history": history.model_copy(update={"rows": rows})}
            ),
        )
    result = forecast(service, case)
    assert result.forecast.expected_units is None
    assert result.evidence.reliable_days == 55
    assert result.evidence.contiguous_days == 0
    assert result.evidence.stockout_censored_days == (kind == "censored")
    assert result.evidence.other_unreliable_days == (kind == "coverage")


def test_invalid_sales_and_variance_rejected(service):
    with pytest.raises(ValueError, match="nonnegative"):
        forecast(service, origin_case((1,) * 30 + (-1,)))
    valid = forecast(service, origin_case((1,) * 30)).evidence
    for variance in ("NaN", "Infinity", "-1"):
        with pytest.raises(ValueError):
            DemandRegimeEvidence.model_validate(
                valid.model_dump() | {"population_variance": variance}
            )


def weekly_cases():
    # Repeat a seven-day pattern on nonoverlapping dates. Hold the feature date out.
    pattern = (9, 0, 0, 0, 0, 0, 0)
    history = pattern * 8
    target = tuple(pattern[(offset + 1) % 7] for offset in range(30))
    return [
        origin_case(history, actual=target, day=DATE + index * 35 * DAY)
        for index in range(5)
    ]


def test_weekly_selection_replay_and_fallback(service):
    cases = weekly_cases()
    policy = service.fit_policy(cases[:4])
    assert (
        policy.model_dump_json()
        == service.fit_policy(reversed(cases[:4])).model_dump_json()
    )
    assert policy == RegimeSelectionPolicy.model_validate_json(policy.model_dump_json())
    assert (
        forecast(service, cases[3], policy=policy, horizon=30).selection_reason
        == "POLICY_NOT_AVAILABLE_AT_ORIGIN"
    )
    result = forecast(service, cases[4], policy=policy, horizon=30)
    assert result.evidence.regime == DemandRegime.INTERMITTENT
    assert result.evidence.average_demand_interval_days == 7
    assert result.forecast.model_name == BaselineModel.SEASONAL_NAIVE
    assert result.forecast.expected_units == sum(
        row.observed_units_sold for row in cases[4].outcomes.rows
    )
    assert result.selection_reason == "LOWEST_AVAILABLE_BACKTEST_MAE"
    weak = service.fit_policy(cases[:3])
    assert (
        forecast(service, cases[4], policy=weak, horizon=30).selection_reason
        == "NO_QUALIFIED_BACKTEST_METHOD"
    )
    irregular = origin_case((0,) * 29 + (3,), day=DATE + 140 * DAY)
    result = forecast(service, irregular, policy=policy, horizon=30)
    assert result.attempted_methods == (BaselineModel.SEASONAL_NAIVE,)
    assert result.selection_reason == "BACKTEST_METHODS_UNAVAILABLE"
    assert result.forecast.expected_units == 3


def test_seller_isolation_and_duplicate_origins(service):
    cases = weekly_cases()
    policy = service.fit_policy(cases[:4])
    foreign = UUID(int=500)
    with pytest.raises(PermissionError):
        forecast(
            service, cases[4], policy=policy.model_copy(update={"seller_id": foreign})
        )
    with pytest.raises(PermissionError):
        forecast(
            service,
            replace(
                cases[4],
                snapshot=cases[4].snapshot.model_copy(update={"seller_id": foreign}),
            ),
        )
    with pytest.raises(PermissionError):
        service.fit_policy(
            [
                replace(
                    cases[0],
                    outcomes=cases[0].outcomes.model_copy(
                        update={"seller_id": foreign}
                    ),
                )
            ]
        )
    with pytest.raises(ValueError, match="Duplicate"):
        service.fit_policy([cases[0], cases[0]])


def test_regular_short_window_can_win_but_overlapping_dates_do_not_qualify(service):
    history = (3,) * 49 + (8,) * 7
    cases = [
        origin_case(history, actual=(8,) * 30, day=DATE + index * 35 * DAY)
        for index in range(5)
    ]
    policy = service.fit_policy(cases[:4])
    assert (
        forecast(service, cases[4], policy=policy).forecast.model_name
        == BaselineModel.MOVING_AVERAGE
    )

    overlapping = [
        origin_case(history, actual=(8,) * 30, day=DATE + index * DAY)
        for index in range(4)
    ]
    ranking = service.fit_policy(overlapping).rankings[0]
    assert (
        ranking.distinct_origin_dates == 4 and ranking.nonoverlapping_origin_dates == 1
    )
    assert ranking.preferred_methods == ()


def test_offline_cli(service, tmp_path, monkeypatch, capsys):
    from scripts.backtest_demand_regimes import main

    cases = weekly_cases()[:4]
    entries = []
    for index, case in enumerate(cases):
        snapshot, outcomes = f"snapshot-{index}.json", f"outcomes-{index}.json"
        (tmp_path / snapshot).write_text(case.snapshot.model_dump_json())
        (tmp_path / outcomes).write_text(case.outcomes.model_dump_json())
        entries.append(
            dict(
                forecast_origin=case.forecast_origin.isoformat(),
                snapshot=snapshot,
                outcomes=outcomes,
            )
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": entries}))
    monkeypatch.setattr(
        "sys.argv",
        ["backtest", "--seller-id", str(SELLER), "--manifest", str(manifest)],
    )
    main()
    assert RegimeSelectionPolicy.model_validate_json(
        capsys.readouterr().out
    ) == service.fit_policy(cases)


def test_optional_intermittent_candidates():
    pytest.importorskip("statsforecast")
    service = RegimeForecastService(
        StatisticalForecastService(
            authorized_seller_id=SELLER, enable_statsforecast=True
        )
    )
    ranking = service.fit_policy(weekly_cases()[:4]).rankings[0]
    scores = {score.method: score for score in ranking.scores}
    for model in (BaselineModel.CROSTON_SBA, BaselineModel.TSB, BaselineModel.ADIDA):
        assert scores[model].scored_rows == 4
        assert scores[model].mae is not None and scores[model].mae >= 0
