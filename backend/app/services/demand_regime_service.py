"""Classify point-in-time history and apply an offline, seller-scoped policy."""

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Context, Decimal, localcontext
from typing import Iterable
from uuid import UUID

from app.schemas.demand_regime import (
    DemandRegime,
    DemandRegimeEvidence,
    RegimeForecast,
    RegimeModelScore,
    RegimeRanking,
    RegimeSelectionPolicy,
)
from app.schemas.forecast_features import (
    FEATURE_VERSION,
    ForecastHorizon,
    ForecastSourceSnapshot,
)
from app.schemas.statistical_forecast import (
    BaselineModel,
    DataSufficiencyStatus,
    EvidenceStatus,
    ForecastResult,
)
from app.services.forecast_backtesting_service import HORIZONS, RollingOriginCase
from app.services.forecast_feature_builder import eligible_observed_sales
from app.services.historical_dataset_service import DAY
from app.services.statistical_forecast_service import (
    STATSFORECAST_MODELS,
    PreparedForecast,
    StatisticalForecastService,
)

POLICY_VERSION = "demand-regime-v1"
MINIMUM_BACKTEST_DATES = 4
MINIMUM_RELIABLE_TAIL_DAYS = 14
MINIMUM_SINGLE_EVENT_DAYS = 28
_REGULAR_MODELS = (
    BaselineModel.MOVING_AVERAGE,
    BaselineModel.SEASONAL_NAIVE,
    BaselineModel.EXPONENTIAL_SMOOTHING,
)
_SPARSE_MODELS = (
    BaselineModel.SEASONAL_NAIVE,
    *STATSFORECAST_MODELS,
)
_CANDIDATES = {
    DemandRegime.REGULAR: _REGULAR_MODELS,
    DemandRegime.INTERMITTENT: _SPARSE_MODELS,
    DemandRegime.POTENTIALLY_DECLINING: (
        BaselineModel.MOVING_AVERAGE,
        BaselineModel.TSB,
    ),
}


class DemandRegimeClassifier:
    """Use verified product days and require an uninterrupted tail for forecasts."""

    def __init__(self, baselines: StatisticalForecastService) -> None:
        self.baselines = baselines

    def classify(
        self, snapshot: ForecastSourceSnapshot, *, forecast_origin: datetime
    ) -> DemandRegimeEvidence:
        return self._classify(
            self.baselines._prepare(snapshot, forecast_origin, allow_empty=True)
        )

    def _classify(self, prepared: PreparedForecast) -> DemandRegimeEvidence:
        age = prepared.origin.product_age_days
        rows = prepared.origin.rows[:age]
        sales = prepared.sales[-age:] if age else ()
        reliable = sum(value is not None for value in prepared.origin.sales[:age])
        censored = sum(
            row is not None and row.stockout_indicator is True for row in rows
        )
        missing = rows.count(None)
        days = len(sales)
        positive = [offset for offset, units in enumerate(sales) if units > 0]
        previous, recent = sales[-56:-28], sales[-28:]
        previous_units = sum(previous) if len(previous) == 28 else None
        recent_units = sum(recent) if len(recent) == 28 else None
        with localcontext(Context(prec=38)):
            frequency = Decimal(len(positive)) / days if days else None
            interval = (
                Decimal(positive[-1] - positive[0]) / (len(positive) - 1)
                if len(positive) >= 2
                else None
            )
            variance = (
                Decimal(days * sum(units * units for units in sales) - sum(sales) ** 2)
                / (days * days)
                if days
                else None
            )
            if days < max(
                MINIMUM_RELIABLE_TAIL_DAYS, self.baselines.config.minimum_history_days
            ):
                regime, reason = (
                    DemandRegime.INSUFFICIENT_HISTORY,
                    "MINIMUM_CONTIGUOUS_HISTORY",
                )
            elif len(positive) < 2 and days < MINIMUM_SINGLE_EVENT_DAYS:
                regime, reason = (
                    DemandRegime.INSUFFICIENT_HISTORY,
                    "SHORT_ZERO_ONLY_HISTORY"
                    if not positive
                    else "SHORT_SINGLE_EVENT_HISTORY",
                )
            elif (
                previous_units is not None
                and sum(units > 0 for units in previous) >= 14
                and 4 * sum(recent[:14]) <= previous_units
                and 4 * sum(recent[14:]) <= previous_units
            ):
                regime, reason = (
                    DemandRegime.POTENTIALLY_DECLINING,
                    "SUSTAINED_REDUCTION_AFTER_FREQUENT_SALES",
                )
            elif (
                len(positive) < 2
                or days - len(positive)
                >= days * self.baselines.config.intermittent_zero_fraction
            ):
                regime, reason = (
                    DemandRegime.INTERMITTENT,
                    ("OBSERVED_ZERO_ONLY" if not positive else "SPARSE_NONZERO_DAYS"),
                )
            else:
                regime, reason = DemandRegime.REGULAR, "FREQUENT_NONZERO_DAYS"
        return DemandRegimeEvidence(
            regime=regime,
            reason=reason,
            product_age_days=age,
            assessed_days=len(rows),
            reliable_days=reliable,
            contiguous_days=days,
            stockout_censored_days=censored,
            missing_dates=missing,
            other_unreliable_days=len(rows) - reliable - censored - missing,
            nonzero_days=len(positive),
            nonzero_frequency=frequency,
            average_demand_interval_days=interval,
            population_variance=variance,
            previous_28_units=previous_units,
            recent_28_units=recent_units,
        )


class RegimeForecastService:
    """Evaluate candidates offline and apply only precomputed rankings at inference."""

    def __init__(self, baselines: StatisticalForecastService) -> None:
        self.baselines = baselines
        self.classifier = DemandRegimeClassifier(baselines)

    @staticmethod
    def _mean(
        prepared: PreparedForecast,
        evidence: DemandRegimeEvidence,
        horizon: ForecastHorizon,
    ) -> Decimal:
        sales = prepared.sales[-evidence.contiguous_days :]
        if evidence.regime == DemandRegime.POTENTIALLY_DECLINING:
            sales = sales[-28:]
        with localcontext(Context(prec=38)):
            return Decimal(sum(sales) * horizon) / len(sales)

    def fit_policy(self, cases: Iterable[RollingOriginCase]) -> RegimeSelectionPolicy:
        """Rank methods on archived forecasts and complete future outcomes."""
        seen = set()
        dates: set[date] = set()
        cutoffs: list[datetime] = []
        outcomes: dict[tuple[UUID, date], int] = {}
        groups: dict[
            tuple[DemandRegime, ForecastHorizon],
            list[tuple[date, int, Decimal, dict[BaselineModel, Decimal]]],
        ] = defaultdict(list)
        for case in cases:
            prepared = self.baselines._prepare(
                case.snapshot, case.forecast_origin, allow_empty=True
            )
            day = prepared.origin.feature_date
            key = (prepared.product_id, day)
            if key in seen:
                raise ValueError("Duplicate product and forecast origin date.")
            seen.add(key)
            dates.add(day)
            cutoffs.append(prepared.origin.forecast_origin)
            labels = self.baselines.features.index_history(
                case.outcomes, prepared.product_id
            )
            observed = []
            for offset in range(1, max(HORIZONS) + 1):
                label_day = day + offset * DAY
                units = eligible_observed_sales(labels.get(label_day))
                if (
                    units is not None
                    and outcomes.setdefault((prepared.product_id, label_day), units)
                    != units
                ):
                    raise ValueError(
                        "Conflicting observed outcomes for the same product-day."
                    )
                observed.append(units)
            evidence = self.classifier._classify(prepared)
            if evidence.regime == DemandRegime.INSUFFICIENT_HISTORY or self._zero_only(
                evidence
            ):
                continue
            prepared = self._eligible_tail(prepared, evidence)
            for horizon in HORIZONS:
                actual = [units for units in observed[:horizon] if units is not None]
                if len(actual) != horizon:
                    continue
                cutoffs.append(case.outcomes.as_of_timestamp)
                predictions = {}
                for method in _CANDIDATES[evidence.regime]:
                    forecast = self.baselines._forecast(
                        prepared, horizon, method, prepared.origin.forecast_origin
                    )
                    if forecast.expected_units is not None:
                        predictions[method] = forecast.expected_units
                groups[(evidence.regime, horizon)].append(
                    (
                        day,
                        sum(actual),
                        self._mean(prepared, evidence, horizon),
                        predictions,
                    )
                )
        if not dates:
            raise ValueError("At least one archived forecast origin is required.")
        with localcontext(Context(prec=38)):
            rankings = []
            for (regime, horizon), rows in sorted(groups.items()):
                origin_dates = sorted({row[0] for row in rows})
                last_disjoint = None
                disjoint_dates = 0
                for day in origin_dates:
                    if last_disjoint is None or day - last_disjoint >= horizon * DAY:
                        disjoint_dates += 1
                        last_disjoint = day
                anchor_errors = sorted(
                    abs(mean - actual) for _, actual, mean, _ in rows
                )
                anchor = sum(anchor_errors, Decimal(0)) / len(rows)
                scores = [
                    RegimeModelScore(
                        method="historical_mean", scored_rows=len(rows), mae=anchor
                    )
                ]
                preferred = []
                for method in _CANDIDATES[regime]:
                    errors = [
                        abs(predictions[method] - actual)
                        for _, actual, _, predictions in rows
                        if method in predictions
                    ]
                    mae = (
                        sum(sorted(errors), Decimal(0)) / len(errors)
                        if errors
                        else None
                    )
                    scores.append(
                        RegimeModelScore(
                            method=method, scored_rows=len(errors), mae=mae
                        )
                    )
                    if (
                        disjoint_dates >= MINIMUM_BACKTEST_DATES
                        and len(errors) == len(rows)
                        and mae is not None
                        and mae < anchor
                    ):
                        preferred.append((mae, method))
                rankings.append(
                    RegimeRanking(
                        regime=regime,
                        horizon_days=horizon,
                        eligible_rows=len(rows),
                        distinct_origin_dates=len(origin_dates),
                        nonoverlapping_origin_dates=disjoint_dates,
                        scores=tuple(scores),
                        preferred_methods=tuple(
                            method for _, method in sorted(preferred)
                        ),
                    )
                )
        return RegimeSelectionPolicy(
            seller_id=self.baselines.seller_id,
            baseline_config=self.baselines.config,
            statsforecast_version=self.baselines.statsforecast_version,
            statsforecast_dependencies=self.baselines.statsforecast_dependencies,
            available_at=max(cutoffs),
            first_origin_date=min(dates),
            last_origin_date=max(dates),
            rankings=tuple(rankings),
        )

    @staticmethod
    def _zero_only(evidence: DemandRegimeEvidence) -> bool:
        return (
            evidence.nonzero_days == 0
            and evidence.regime != DemandRegime.POTENTIALLY_DECLINING
        )

    @staticmethod
    def _eligible_tail(
        prepared: PreparedForecast, evidence: DemandRegimeEvidence
    ) -> PreparedForecast:
        return PreparedForecast(
            prepared.product_id,
            prepared.origin,
            prepared.captured_at,
            prepared.sales[-evidence.contiguous_days :]
            if evidence.contiguous_days
            else (),
        )

    def forecast(
        self,
        snapshot: ForecastSourceSnapshot,
        *,
        forecast_origin: datetime,
        horizon_days: ForecastHorizon,
        policy: RegimeSelectionPolicy | None = None,
        generated_at: datetime | None = None,
    ) -> RegimeForecast:
        if policy is not None and policy.seller_id != self.baselines.seller_id:
            raise PermissionError("Regime policy outside authorized seller scope.")
        generated = generated_at or datetime.now(timezone.utc)
        if horizon_days not in HORIZONS or generated.utcoffset() is None:
            raise ValueError(
                "An aware generation time and a supported horizon are required."
            )
        prepared = self.baselines._prepare(snapshot, forecast_origin, allow_empty=True)
        evidence = self.classifier._classify(prepared)
        prepared = self._eligible_tail(prepared, evidence)
        regime = evidence.regime
        if regime == DemandRegime.INSUFFICIENT_HISTORY:
            return RegimeForecast(
                forecast=self._fallback(
                    prepared, horizon_days, generated, None, evidence.reason
                ),
                evidence=evidence,
                selection_reason=evidence.reason,
            )
        if self._zero_only(evidence):
            return RegimeForecast(
                forecast=self._fallback(
                    prepared, horizon_days, generated, Decimal(0), None
                ),
                evidence=evidence,
                selection_reason="OBSERVED_ZERO_HISTORY",
            )
        attempted = []
        reason = "NO_BACKTEST_POLICY"
        if policy is not None:
            if policy.available_at >= prepared.origin.forecast_origin:
                reason = "POLICY_NOT_AVAILABLE_AT_ORIGIN"
            elif policy.baseline_config != self.baselines.config:
                reason = "POLICY_BASELINE_CONFIG_MISMATCH"
            else:
                reason = "NO_QUALIFIED_BACKTEST_METHOD"
                ranking = next(
                    (
                        item
                        for item in policy.rankings
                        if (item.regime, item.horizon_days) == (regime, horizon_days)
                    ),
                    None,
                )
                if ranking is not None:
                    for method in dict.fromkeys(ranking.preferred_methods):
                        if method not in _CANDIDATES[regime]:
                            continue
                        attempted.append(method)
                        if method in STATSFORECAST_MODELS and (
                            policy.statsforecast_version
                            != self.baselines.statsforecast_version
                            or policy.statsforecast_dependencies
                            != self.baselines.statsforecast_dependencies
                        ):
                            continue
                        result = self.baselines._forecast(
                            prepared, horizon_days, method, generated
                        )
                        if result.expected_units is not None:
                            return RegimeForecast(
                                forecast=result,
                                evidence=evidence,
                                selection_reason="LOWEST_AVAILABLE_BACKTEST_MAE",
                                policy_available_at=policy.available_at,
                                attempted_methods=tuple(attempted),
                            )
                    if attempted:
                        reason = "BACKTEST_METHODS_UNAVAILABLE"
        return RegimeForecast(
            forecast=self._fallback(
                prepared,
                horizon_days,
                generated,
                self._mean(prepared, evidence, horizon_days),
                reason,
            ),
            evidence=evidence,
            selection_reason=reason,
            policy_available_at=policy.available_at if policy is not None else None,
            attempted_methods=tuple(attempted),
        )

    def _fallback(
        self,
        prepared: PreparedForecast,
        horizon: ForecastHorizon,
        generated: datetime,
        units: Decimal | None,
        reason: str | None,
    ) -> ForecastResult:
        day = prepared.origin.feature_date
        sufficient = units is not None
        return ForecastResult(
            seller_id=self.baselines.seller_id,
            product_id=prepared.product_id,
            forecast_origin=prepared.origin.forecast_origin,
            horizon_days=horizon,
            target_start_date=day + DAY,
            target_end_date=day + horizon * DAY,
            expected_units=units,
            requested_model=BaselineModel.AUTO,
            model_name="historical_mean" if sufficient else None,
            model_version=POLICY_VERSION,
            data_sufficiency_status=DataSufficiencyStatus.SUFFICIENT
            if sufficient
            else DataSufficiencyStatus.INSUFFICIENT,
            evidence_status=EvidenceStatus.ELIGIBLE_OBSERVED_SALES
            if sufficient
            else EvidenceStatus.UNAVAILABLE,
            generated_at=generated.astimezone(timezone.utc),
            fallback_reason=reason,
            contiguous_history_days=len(prepared.sales),
            data_cutoff=prepared.captured_at,
            feature_version=FEATURE_VERSION,
        )
