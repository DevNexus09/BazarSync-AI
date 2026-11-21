"""Offline benchmark forecast and evaluation contracts."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.forecast_features import FeatureModel, ForecastHorizon
from app.schemas.forecast_uncertainty import ForecastInterval


class BaselineModel(StrEnum):
    AUTO = "auto"
    NAIVE = "naive"
    SEASONAL_NAIVE = "seasonal_naive"
    MOVING_AVERAGE = "moving_average"
    EXPONENTIAL_SMOOTHING = "exponential_smoothing"
    CROSTON_CLASSIC = "croston_classic"
    CROSTON_SBA = "croston_sba"
    CROSTON_OPTIMIZED = "croston_optimized"
    TSB = "tsb"
    ADIDA = "adida"


class BaselineConfig(FeatureModel):
    minimum_history_days: int = Field(default=14, ge=1, le=366)
    lookback_days: int = Field(default=90, ge=1, le=366)
    moving_average_days: int = Field(default=7, ge=1, le=366)
    smoothing_minimum_days: int = Field(default=14, ge=2, le=366)
    smoothing_alpha: Decimal = Field(default=Decimal("0.3"), gt=0, le=1)
    seasonal_minimum_days: int = Field(default=21, ge=14, le=366)
    seasonal_error_ratio: Decimal = Field(default=Decimal("0.8"), gt=0, lt=1)
    intermittent_minimum_days: int = Field(default=28, ge=2, le=366)
    intermittent_zero_fraction: Decimal = Field(default=Decimal("0.5"), gt=0, lt=1)
    high_volume_units_per_day: Decimal = Field(default=Decimal("5"), gt=0)
    new_product_age_days: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def check_minimum(self) -> Self:
        if self.lookback_days < self.minimum_history_days:
            raise ValueError("Lookback must cover the minimum history.")
        return self


class DataSufficiencyStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    MODEL_NOT_APPLICABLE = "MODEL_NOT_APPLICABLE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


class EvidenceStatus(StrEnum):
    ELIGIBLE_OBSERVED_SALES = "ELIGIBLE_OBSERVED_SALES"
    UNAVAILABLE = "UNAVAILABLE"


class ForecastResult(FeatureModel):
    seller_id: UUID
    product_id: UUID
    forecast_origin: AwareDatetime
    horizon_days: ForecastHorizon
    target_start_date: date
    target_end_date: date
    expected_units: Decimal | None = Field(ge=0)
    requested_model: BaselineModel
    model_name: BaselineModel | Literal["historical_mean", "catboost"] | None
    model_version: str
    data_sufficiency_status: DataSufficiencyStatus
    evidence_status: EvidenceStatus
    generated_at: AwareDatetime
    fallback_reason: str | None
    contiguous_history_days: int = Field(ge=0)
    data_cutoff: AwareDatetime
    feature_version: str
    prediction_interval: ForecastInterval | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def check_evidence(self) -> Self:
        if self.data_sufficiency_status == DataSufficiencyStatus.SUFFICIENT:
            if (
                self.expected_units is None
                or self.model_name in {None, BaselineModel.AUTO}
                or self.evidence_status != EvidenceStatus.ELIGIBLE_OBSERVED_SALES
            ):
                raise ValueError(
                    "Sufficient forecasts require an estimate, model, and observed sales evidence."
                )
        elif (
            self.expected_units is not None
            or self.model_name is not None
            or not self.fallback_reason
            or self.evidence_status != EvidenceStatus.UNAVAILABLE
        ):
            raise ValueError(
                "Unavailable forecasts require an explicit reason and no estimate."
            )
        if self.prediction_interval is not None:
            self.prediction_interval.validate_point(
                self.expected_units, self.forecast_origin, self.target_start_date
            )
        return self


class ProductCohort(StrEnum):
    ALL = "all"
    NEW = "new"
    HIGH_VOLUME = "high_volume"
    LOW_VOLUME = "low_volume"
    INTERMITTENT = "intermittent"
    ZERO_DEMAND = "zero_demand"
    UNKNOWN = "unknown"


class BacktestFold(FeatureModel):
    forecast: ForecastResult
    cohort: ProductCohort
    observed_target_units: int | None = Field(ge=0)
    eligible_target_days: int = Field(ge=0)
    outcome_extract_cutoff: AwareDatetime
    mase_scale: Decimal | None = Field(gt=0)


class BacktestMetrics(FeatureModel):
    model: BaselineModel
    horizon_days: ForecastHorizon
    cohort: ProductCohort
    folds: int
    forecasted_folds: int
    eligible_target_folds: int
    scored_folds: int
    mase_scored_folds: int
    mae: Decimal | None
    wape_percent: Decimal | None
    mase: Decimal | None
    bias_units: Decimal | None


class BacktestReport(FeatureModel):
    version: Literal["rolling-origin-v1"] = "rolling-origin-v1"
    seller_id: UUID
    config: BaselineConfig
    statsforecast_version: str | None
    statsforecast_dependencies: dict[str, str]
    folds: tuple[BacktestFold, ...]
    metrics: tuple[BacktestMetrics, ...]
