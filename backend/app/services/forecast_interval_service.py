"""Chronological residual intervals and later-origin empirical evaluation."""

from collections import defaultdict
from datetime import date
from decimal import Context, Decimal, localcontext
from hashlib import sha256
from math import ceil
from typing import Iterable, Literal, Self, cast
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.demand_regime import DemandRegime
from app.schemas.forecast_features import FeatureModel, ForecastHorizon
from app.schemas.forecast_inference import LeadTimeDemandCalibration
from app.schemas.forecast_uncertainty import (
    CalibrationPeriod,
    ForecastInterval,
    IntervalStatus,
)
from app.schemas.ml_forecast import MLForecastResult
from app.schemas.statistical_forecast import ForecastResult
from app.services.historical_dataset_service import BUSINESS_TIMEZONE, DAY, _opening

PointForecast = ForecastResult | MLForecastResult


class IntervalSample(FeatureModel):
    forecast: PointForecast
    regime: DemandRegime
    actual_units: int | None = Field(ge=0)
    outcome_extract_cutoff: AwareDatetime


class ResidualKey(FeatureModel):
    product_id: UUID
    horizon_days: ForecastHorizon
    regime: DemandRegime
    model_name: str
    model_version: str
    feature_version: str
    model_sha256: str | None = None
    feature_schema_sha256: str | None = None


class ResidualProfile(FeatureModel):
    key: ResidualKey
    radius_units: Decimal = Field(ge=1)
    period: CalibrationPeriod


class IntervalCalibration(FeatureModel):
    method: Literal["chronological_absolute_residual_v1"] = (
        "chronological_absolute_residual_v1"
    )
    seller_id: UUID
    forecast_context: str = Field(min_length=1)
    nominal_level: Decimal = Field(gt=0, lt=1)
    test_start_date: date
    profiles: tuple[ResidualProfile, ...]

    @model_validator(mode="after")
    def check_profiles(self) -> Self:
        if len({profile.key for profile in self.profiles}) != len(self.profiles):
            raise ValueError("Duplicate calibration profile.")
        for profile in self.profiles:
            if (
                profile.period.last_target_date
                != profile.period.last_origin.astimezone(BUSINESS_TIMEZONE).date()
                + profile.key.horizon_days * DAY
                or profile.period.available_at
                < _opening(profile.period.last_target_date + DAY)
                or profile.period.last_target_date >= self.test_start_date
                or profile.period.available_at >= _opening(self.test_start_date)
                or ceil((profile.period.scored_windows + 1) * self.nominal_level)
                > profile.period.scored_windows
            ):
                raise ValueError("Invalid calibration support or test boundary.")
        return self


class IntervalMetrics(FeatureModel):
    horizon_days: ForecastHorizon
    regime: DemandRegime | None
    test_rows: int = Field(ge=0)
    eligible_outcome_rows: int = Field(ge=0)
    intervals_issued: int = Field(ge=0)
    scored_rows: int = Field(ge=0)
    empirical_coverage: Decimal | None = Field(ge=0, le=1)
    average_width_units: Decimal | None = Field(ge=0)
    underprediction_frequency: Decimal | None = Field(ge=0, le=1)
    overprediction_frequency: Decimal | None = Field(ge=0, le=1)


class IntervalBacktestReport(FeatureModel):
    calibration: IntervalCalibration
    eligible_calibration_rows: int = Field(ge=0)
    overlapping_calibration_rows: int = Field(ge=0)
    embargoed_rows: int = Field(ge=0)
    test_end_date: date | None
    metrics: tuple[IntervalMetrics, ...]


def _key(point: PointForecast, regime: DemandRegime) -> ResidualKey:
    if isinstance(point, MLForecastResult):
        model_name = "catboost"
        model_sha256 = point.model_sha256
        feature_schema_sha256 = point.feature_schema_sha256
    else:
        model_name = str(point.model_name)
        model_sha256 = None
        feature_schema_sha256 = None
    return ResidualKey(
        product_id=point.product_id,
        horizon_days=point.horizon_days,
        regime=regime,
        model_name=model_name,
        model_version=point.model_version,
        feature_version=point.feature_version,
        model_sha256=model_sha256,
        feature_schema_sha256=feature_schema_sha256,
    )


def _validate_window(point: PointForecast) -> date:
    origin_date = point.forecast_origin.astimezone(BUSINESS_TIMEZONE).date()
    if (
        point.target_start_date != origin_date + DAY
        or point.target_end_date != origin_date + point.horizon_days * DAY
    ):
        raise ValueError("Forecast horizon and target dates do not agree.")
    return origin_date


class ForecastIntervalService:
    def __init__(
        self,
        *,
        seller_id: UUID,
        forecast_context: str,
        calibration: IntervalCalibration | None = None,
    ) -> None:
        if calibration is not None and calibration.seller_id != seller_id:
            raise PermissionError(
                "Interval calibration outside authorized seller scope."
            )
        self.seller_id = seller_id
        self.calibration = calibration
        self.context_matches = (
            calibration is not None and calibration.forecast_context == forecast_context
        )
        self.profiles = (
            {profile.key: profile for profile in calibration.profiles}
            if self.context_matches and calibration is not None
            else {}
        )

    def attach[T: PointForecast](self, point: T, *, regime: DemandRegime) -> T:
        if point.seller_id != self.seller_id:
            raise PermissionError("Forecast outside authorized seller scope.")
        _validate_window(point)
        interval = self._interval(point, regime)
        return cast(
            T,
            type(point).model_validate(
                {**point.model_dump(), "prediction_interval": interval}
            ),
        )

    def _interval(self, point: PointForecast, regime: DemandRegime) -> ForecastInterval:
        calibration = self.calibration
        if point.expected_units is None:
            return ForecastInterval(
                status=IntervalStatus.INSUFFICIENT_DATA,
                reason="POINT_FORECAST_UNAVAILABLE",
            )
        if calibration is None or not self.context_matches:
            return ForecastInterval(
                status=IntervalStatus.UNCALIBRATED,
                reason="NO_CALIBRATION"
                if calibration is None
                else "FORECAST_CONTEXT_MISMATCH",
            )
        if (
            point.forecast_origin.astimezone(BUSINESS_TIMEZONE).date()
            < calibration.test_start_date
        ):
            return ForecastInterval(
                status=IntervalStatus.UNCALIBRATED,
                reason="CALIBRATION_NOT_AVAILABLE_AT_ORIGIN",
            )
        profile = self.profiles.get(_key(point, regime))
        if profile is None:
            return ForecastInterval(
                status=IntervalStatus.INSUFFICIENT_DATA,
                reason="NO_MATCHING_RESIDUAL_PROFILE",
            )
        with localcontext(Context(prec=38)):
            return ForecastInterval(
                status=IntervalStatus.EMPIRICAL_UNVALIDATED,
                lower_bound=max(
                    Decimal(0), point.expected_units - profile.radius_units
                ),
                upper_bound=point.expected_units + profile.radius_units,
                nominal_level=calibration.nominal_level,
                calibration_method=calibration.method,
                calibration_period=profile.period,
            )


def backtest_intervals(
    samples: Iterable[IntervalSample],
    *,
    seller_id: UUID,
    forecast_context: str,
    test_start_date: date,
    nominal_level: Decimal = Decimal("0.90"),
) -> IntervalBacktestReport:
    if not nominal_level.is_finite() or not 0 < nominal_level < 1:
        raise ValueError(
            "Nominal interval level must lie strictly between zero and one."
        )
    calibration_rows: dict[ResidualKey, list[IntervalSample]] = defaultdict(list)
    test_rows = []
    embargoed = 0
    seen = set()
    for row in samples:
        point = row.forecast
        if point.seller_id != seller_id:
            raise PermissionError("Interval sample outside authorized seller scope.")
        origin_date = _validate_window(point)
        key = _key(point, row.regime)
        identity = (point.product_id, origin_date, point.horizon_days)
        if identity in seen:
            raise ValueError("Duplicate product, origin date, and horizon.")
        seen.add(identity)
        if row.actual_units is not None and row.outcome_extract_cutoff < _opening(
            point.target_end_date + DAY
        ):
            raise ValueError("Observed outcomes require a closed target window.")
        if origin_date >= test_start_date:
            test_rows.append((origin_date, row))
        elif row.actual_units is not None and point.expected_units is not None:
            if (
                point.target_end_date >= test_start_date
                or row.outcome_extract_cutoff >= _opening(test_start_date)
            ):
                embargoed += 1
            else:
                calibration_rows[key].append(row)
    with localcontext(Context(prec=38)):
        profiles = []
        overlap_count = 0
        for key, rows in sorted(
            calibration_rows.items(), key=lambda entry: entry[0].model_dump_json()
        ):
            retained: list[IntervalSample] = []
            errors = []
            for row in sorted(rows, key=lambda sample: sample.forecast.forecast_origin):
                if (
                    retained
                    and row.forecast.target_start_date
                    <= retained[-1].forecast.target_end_date
                ):
                    overlap_count += 1
                    continue
                expected, actual = row.forecast.expected_units, row.actual_units
                assert expected is not None and actual is not None
                retained.append(row)
                errors.append(abs(Decimal(actual) - expected))
            rank = ceil((len(errors) + 1) * nominal_level)
            if len(errors) < 20 or rank > len(errors):
                continue
            profiles.append(
                ResidualProfile(
                    key=key,
                    radius_units=max(Decimal(1), sorted(errors)[rank - 1]),
                    period=CalibrationPeriod(
                        first_origin=retained[0].forecast.forecast_origin,
                        last_origin=retained[-1].forecast.forecast_origin,
                        last_target_date=retained[-1].forecast.target_end_date,
                        available_at=max(
                            row.outcome_extract_cutoff for row in retained
                        ),
                        scored_windows=len(retained),
                    ),
                )
            )
        calibration = IntervalCalibration(
            seller_id=seller_id,
            forecast_context=forecast_context,
            nominal_level=nominal_level,
            test_start_date=test_start_date,
            profiles=tuple(profiles),
        )
        service = ForecastIntervalService(
            seller_id=seller_id,
            forecast_context=forecast_context,
            calibration=calibration,
        )
        groups: dict[
            tuple[ForecastHorizon, DemandRegime | None],
            list[tuple[ForecastInterval, int | None]],
        ] = defaultdict(list)
        for _, row in sorted(
            test_rows,
            key=lambda entry: (
                entry[0],
                entry[1].forecast.product_id,
                entry[1].forecast.horizon_days,
            ),
        ):
            result = service.attach(row.forecast, regime=row.regime)
            assert result.prediction_interval is not None
            for regime in (None, row.regime):
                groups[(result.horizon_days, regime)].append(
                    (result.prediction_interval, row.actual_units)
                )
        metrics = tuple(
            _metrics(horizon, regime, group)
            for (horizon, regime), group in sorted(
                groups.items(), key=lambda entry: (entry[0][0], entry[0][1] or "")
            )
        )
    return IntervalBacktestReport(
        calibration=calibration,
        eligible_calibration_rows=sum(map(len, calibration_rows.values())),
        overlapping_calibration_rows=overlap_count,
        embargoed_rows=embargoed,
        test_end_date=max((origin for origin, _ in test_rows), default=None),
        metrics=metrics,
    )


def _metrics(
    horizon: ForecastHorizon,
    regime: DemandRegime | None,
    group: list[tuple[ForecastInterval, int | None]],
) -> IntervalMetrics:
    widths = []
    under = over = eligible = issued = 0
    for interval, actual in group:
        lower, upper = interval.lower_bound, interval.upper_bound
        eligible += actual is not None
        issued += lower is not None
        if actual is None or lower is None or upper is None:
            continue
        widths.append(upper - lower)
        under += actual > upper
        over += actual < lower
    n = len(widths)
    return IntervalMetrics(
        horizon_days=horizon,
        regime=regime,
        test_rows=len(group),
        eligible_outcome_rows=eligible,
        intervals_issued=issued,
        scored_rows=n,
        empirical_coverage=Decimal(n - under - over) / n if n else None,
        average_width_units=sum(widths, Decimal(0)) / n if n else None,
        underprediction_frequency=Decimal(under) / n if n else None,
        overprediction_frequency=Decimal(over) / n if n else None,
    )


def validate_reorder_bound(
    samples: Iterable[IntervalSample],
    *,
    seller_id: UUID,
    product_id: UUID,
    horizon_days: ForecastHorizon,
    model_sha256: str,
    test_start_date: date,
    nominal_level: Decimal = Decimal("0.90"),
) -> LeadTimeDemandCalibration | None:
    """Fit a Task 13 residual radius and validate the upper bound on separate windows."""
    selected = tuple(
        sorted(
            (
                row
                for row in samples
                if isinstance(row.forecast, MLForecastResult)
                and row.forecast.product_id == product_id
                and row.forecast.horizon_days == horizon_days
                and row.forecast.model_sha256 == model_sha256
                and row.regime == DemandRegime.REGULAR
            ),
            key=lambda row: row.forecast.forecast_origin,
        )
    )
    if len({_key(row.forecast, row.regime) for row in selected}) > 1:
        raise ValueError(
            "Lead-time validation requires a single model and feature version."
        )
    report = backtest_intervals(
        selected,
        seller_id=seller_id,
        forecast_context=model_sha256,
        test_start_date=test_start_date,
        nominal_level=nominal_level,
    )
    if not report.calibration.profiles:
        return None
    (profile,) = report.calibration.profiles
    retained: list[IntervalSample] = []
    within = 0
    for row in selected:
        point = row.forecast
        if (
            point.forecast_origin.astimezone(BUSINESS_TIMEZONE).date() < test_start_date
            or row.actual_units is None
            or point.expected_units is None
            or (
                retained
                and point.target_start_date <= retained[-1].forecast.target_end_date
            )
        ):
            continue
        retained.append(row)
        within += row.actual_units <= point.expected_units + profile.radius_units
    if len(retained) < 20:
        return None
    lineage = sha256()
    for row in selected:
        lineage.update(row.model_dump_json().encode())
        lineage.update(b"\n")
    return LeadTimeDemandCalibration(
        product_id=product_id,
        model_sha256=model_sha256,
        radius_units=profile.radius_units,
        nominal_level=nominal_level,
        calibration=profile.period,
        validation_first_origin=retained[0]
        .forecast.forecast_origin.astimezone(BUSINESS_TIMEZONE)
        .date(),
        validation_last_origin=retained[-1]
        .forecast.forecast_origin.astimezone(BUSINESS_TIMEZONE)
        .date(),
        validation_outcomes_available_at=max(
            row.outcome_extract_cutoff for row in retained
        ),
        validation_windows=len(retained),
        within_upper_bound=within,
        validation_lineage_sha256=lineage.hexdigest(),
    )
