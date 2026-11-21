"""Replay a fixed Task 12 forecaster against archived Task 8 outcomes."""

from datetime import date
from hashlib import sha256
import json
from typing import Iterable, Iterator
from uuid import UUID

from app.schemas.demand_regime import RegimeSelectionPolicy
from app.services.demand_regime_service import POLICY_VERSION, RegimeForecastService
from app.services.forecast_backtesting_service import HORIZONS, RollingOriginCase
from app.services.forecast_feature_builder import eligible_observed_sales
from app.services.forecast_interval_service import IntervalSample
from app.services.historical_dataset_service import DAY


def regime_forecast_context(
    forecaster: RegimeForecastService, policy: RegimeSelectionPolicy | None
) -> str:
    baselines = forecaster.baselines
    if policy is not None:
        if policy.seller_id != baselines.seller_id:
            raise PermissionError("Regime policy outside authorized seller scope.")
        if policy.baseline_config != baselines.config:
            raise ValueError(
                "Regime policy configuration must match the replay forecaster."
            )
    payload = {
        "version": POLICY_VERSION,
        "config": baselines.config.model_dump(mode="json"),
        "statsforecast_version": baselines.statsforecast_version,
        "statsforecast_dependencies": baselines.statsforecast_dependencies,
        "policy": policy.model_dump(mode="json") if policy is not None else None,
    }
    return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def replay_regime_intervals(
    cases: Iterable[RollingOriginCase],
    forecaster: RegimeForecastService,
    *,
    policy: RegimeSelectionPolicy | None = None,
) -> Iterator[IntervalSample]:
    regime_forecast_context(forecaster, policy)
    observed: dict[tuple[UUID, date], int] = {}
    for case in cases:
        if policy is not None and policy.available_at >= case.forecast_origin:
            raise ValueError(
                "The regime policy must precede every calibration and test origin."
            )
        labels = forecaster.baselines.features.index_history(
            case.outcomes, case.snapshot.product_id
        )
        for horizon in HORIZONS:
            result = forecaster.forecast(
                case.snapshot,
                forecast_origin=case.forecast_origin,
                horizon_days=horizon,
                policy=policy,
                generated_at=case.forecast_origin,
            )
            point = result.forecast
            target = []
            for offset in range(horizon):
                day = point.target_start_date + offset * DAY
                units = eligible_observed_sales(labels.get(day))
                if units is not None:
                    key = (point.product_id, day)
                    if observed.setdefault(key, units) != units:
                        raise ValueError(
                            "Conflicting observed outcomes for the same product-day."
                        )
                    target.append(units)
            yield IntervalSample(
                forecast=point,
                regime=result.evidence.regime,
                actual_units=sum(target) if len(target) == horizon else None,
                outcome_extract_cutoff=case.outcomes.as_of_timestamp,
            )
