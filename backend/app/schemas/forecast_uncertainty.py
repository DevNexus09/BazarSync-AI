"""Optional interval metadata shared by statistical and ML forecasts."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.forecast_features import FeatureModel


class IntervalStatus(StrEnum):
    EMPIRICAL_UNVALIDATED = "empirical_unvalidated"
    UNCALIBRATED = "uncalibrated"
    INSUFFICIENT_DATA = "insufficient_data"


class CalibrationPeriod(FeatureModel):
    first_origin: AwareDatetime
    last_origin: AwareDatetime
    last_target_date: date
    available_at: AwareDatetime
    scored_windows: int = Field(ge=20)

    @model_validator(mode="after")
    def check_period(self) -> Self:
        if not self.first_origin <= self.last_origin < self.available_at:
            raise ValueError("Invalid calibration period.")
        return self


class ForecastInterval(FeatureModel):
    status: IntervalStatus
    lower_bound: Decimal | None = Field(default=None, ge=0)
    upper_bound: Decimal | None = Field(default=None, ge=0)
    nominal_level: Decimal | None = Field(default=None, gt=0, lt=1)
    calibration_method: Literal["chronological_absolute_residual_v1"] | None = None
    calibration_period: CalibrationPeriod | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def check_bounds(self) -> Self:
        fields = (
            self.lower_bound,
            self.upper_bound,
            self.nominal_level,
            self.calibration_method,
            self.calibration_period,
        )
        if self.status == IntervalStatus.EMPIRICAL_UNVALIDATED:
            if any(value is None for value in fields) or self.reason is not None:
                raise ValueError(
                    "An empirical interval requires complete bounds and calibration metadata."
                )
            assert self.lower_bound is not None and self.upper_bound is not None
            if self.upper_bound - self.lower_bound < 1:
                raise ValueError("The forecast interval must span at least one unit.")
        elif any(value is not None for value in fields) or not self.reason:
            raise ValueError(
                "Unavailable intervals require a reason and no bounds or calibration claim."
            )
        return self

    def validate_point(
        self, point: Decimal | None, origin: datetime, target_start: date
    ) -> None:
        if self.status != IntervalStatus.EMPIRICAL_UNVALIDATED:
            return
        if (
            point is None
            or self.lower_bound is None
            or self.upper_bound is None
            or not self.lower_bound <= point <= self.upper_bound
        ):
            raise ValueError("The interval must contain the point forecast.")
        period = self.calibration_period
        if (
            period is None
            or period.available_at >= origin
            or period.last_target_date >= target_start
        ):
            raise ValueError(
                "Interval calibration must precede the forecast origin and target."
            )
