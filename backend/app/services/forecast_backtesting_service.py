"""Offline expanding-origin comparisons on archived point-in-time snapshots."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Context, Decimal, localcontext
from typing import Iterable
from uuid import UUID

from app.schemas.forecast_features import ForecastHorizon, ForecastSourceSnapshot
from app.schemas.statistical_forecast import (
    BacktestFold,
    BacktestMetrics,
    BacktestReport,
    BaselineModel,
    ProductCohort,
)
from app.services.forecast_feature_builder import eligible_observed_sales
from app.services.historical_dataset_service import DAY, HistoricalDataset
from app.services.statistical_forecast_service import (
    NATIVE_MODELS,
    STATSFORECAST_MODELS,
    StatisticalForecastService,
)

HORIZONS: tuple[ForecastHorizon, ...] = (7, 14, 30)


@dataclass(frozen=True)
class RollingOriginCase:
    forecast_origin: datetime
    snapshot: ForecastSourceSnapshot
    outcomes: HistoricalDataset


def _horizon_mase_scale(sales: tuple[int, ...], horizon: int) -> Decimal | None:
    # Align non-overlapping in-sample totals to the latest observed business day.
    start = len(sales) % horizon
    totals = [sum(sales[i : i + horizon]) for i in range(start, len(sales), horizon)]
    error = sum(
        abs(current - previous) for previous, current in zip(totals, totals[1:])
    )
    return Decimal(error) / (len(totals) - 1) if error else None


def _summaries(folds: list[BacktestFold]) -> tuple[BacktestMetrics, ...]:
    groups: dict[
        tuple[BaselineModel, ForecastHorizon, ProductCohort], list[BacktestFold]
    ] = defaultdict(list)
    for fold in folds:
        forecast = fold.forecast
        for cohort in (ProductCohort.ALL, fold.cohort):
            groups[(forecast.requested_model, forecast.horizon_days, cohort)].append(
                fold
            )
    summaries = []
    for (model, horizon, cohort), group in sorted(groups.items()):
        forecasted = eligible = scored = scaled_count = actual_total = 0
        sum_abs = sum_error = scaled_errors = Decimal(0)
        for fold in group:
            expected, actual = fold.forecast.expected_units, fold.observed_target_units
            forecasted += expected is not None
            eligible += actual is not None
            if expected is None or actual is None:
                continue
            scored += 1
            actual_total += actual
            error = expected - actual
            sum_error += error
            sum_abs += abs(error)
            if fold.mase_scale is not None:
                scaled_count += 1
                scaled_errors += abs(error) / fold.mase_scale
        summaries.append(
            BacktestMetrics(
                model=model,
                horizon_days=horizon,
                cohort=cohort,
                folds=len(group),
                forecasted_folds=forecasted,
                eligible_target_folds=eligible,
                scored_folds=scored,
                mase_scored_folds=scaled_count,
                mae=sum_abs / scored if scored else None,
                wape_percent=Decimal(100) * sum_abs / actual_total
                if actual_total
                else None,
                mase=scaled_errors / scaled_count if scaled_count else None,
                bias_units=sum_error / scored if scored else None,
            )
        )
    return tuple(summaries)


class ForecastBacktestingService:
    def __init__(self, forecaster: StatisticalForecastService) -> None:
        self.forecaster = forecaster

    def evaluate(
        self,
        cases: Iterable[RollingOriginCase],
        *,
        models: tuple[BaselineModel, ...] | None = None,
        horizons: tuple[ForecastHorizon, ...] = HORIZONS,
    ) -> BacktestReport:
        if models is None:
            models = (BaselineModel.AUTO, *NATIVE_MODELS)
            if self.forecaster.statsforecast_version is not None:
                models += tuple(STATSFORECAST_MODELS)
        models = tuple(BaselineModel(model) for model in models)
        if (
            not models
            or len(set(models)) != len(models)
            or not horizons
            or len(set(horizons)) != len(horizons)
            or any(horizon not in HORIZONS for horizon in horizons)
        ):
            raise ValueError("Select unique models and supported, unique horizons.")

        folds = []
        seen: set[tuple[UUID, date]] = set()
        observed_targets: dict[tuple[UUID, date], int] = {}
        with localcontext(Context(prec=38)):
            for case in cases:
                prepared = self.forecaster._prepare(case.snapshot, case.forecast_origin)
                origin = prepared.origin
                key = (prepared.product_id, origin.feature_date)
                if key in seen:
                    raise ValueError(
                        "Duplicate seller-product forecast origin business date."
                    )
                seen.add(key)
                labels = self.forecaster.features.index_history(
                    case.outcomes, prepared.product_id
                )
                cohort = self.forecaster._cohort(prepared)
                targets: list[int | None] = []
                for offset in range(1, max(horizons) + 1):
                    day = origin.feature_date + offset * DAY
                    units = eligible_observed_sales(labels.get(day))
                    if units is not None:
                        target_key = (prepared.product_id, day)
                        if observed_targets.setdefault(target_key, units) != units:
                            raise ValueError(
                                "Conflicting observed outcomes for the same product-day."
                            )
                    targets.append(units)
                for horizon in horizons:
                    actual = [units for units in targets[:horizon] if units is not None]
                    scale = _horizon_mase_scale(prepared.sales, horizon)
                    for model in models:
                        forecast = self.forecaster._forecast(
                            prepared, horizon, model, origin.forecast_origin
                        )
                        folds.append(
                            BacktestFold(
                                forecast=forecast,
                                cohort=cohort,
                                observed_target_units=sum(actual)
                                if len(actual) == horizon
                                else None,
                                eligible_target_days=len(actual),
                                outcome_extract_cutoff=case.outcomes.as_of_timestamp,
                                mase_scale=scale,
                            )
                        )
            folds.sort(
                key=lambda item: (
                    item.forecast.forecast_origin,
                    item.forecast.product_id,
                    item.forecast.horizon_days,
                    item.forecast.requested_model,
                )
            )
            summaries = _summaries(folds)
        return BacktestReport(
            seller_id=self.forecaster.seller_id,
            config=self.forecaster.config,
            statsforecast_version=self.forecaster.statsforecast_version,
            statsforecast_dependencies=self.forecaster.statsforecast_dependencies,
            folds=tuple(folds),
            metrics=summaries,
        )
