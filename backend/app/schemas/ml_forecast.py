"""Offline CatBoost training, evaluation, and inference contracts."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.forecast_features import FeatureModel, ForecastHorizon
from app.schemas.forecast_uncertainty import ForecastInterval
from app.schemas.statistical_forecast import ProductCohort


class EvaluationScope(StrEnum):
    SYNTHETIC = "synthetic"
    HISTORICAL_HOLDOUT = "historical_holdout"


class ModelSelectionStatus(StrEnum):
    SELECTED = "SELECTED"
    BASELINE_RETAINED = "BASELINE_RETAINED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class MLForecastStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CatBoostTrainingConfig(FeatureModel):
    random_seed: int = 20261116
    thread_count: int = Field(default=2, ge=1, le=16)
    iterations: int = Field(default=300, ge=20, le=5000)
    early_stopping_rounds: int = Field(default=30, ge=5, le=500)
    rolling_folds: int = Field(default=3, ge=1, le=10)
    validation_origins: int = Field(default=4, ge=1, le=90)
    test_origins: int = Field(default=6, ge=1, le=180)
    minimum_training_rows: int = Field(default=30, ge=4)
    minimum_test_rows: int = Field(default=3, ge=1)


class CatBoostCandidateResult(FeatureModel):
    candidate_name: str
    loss_function: str
    parameters: dict[str, int | float | str | bool]
    folds: int = Field(ge=0)
    scored_rows: int = Field(ge=0)
    mae: Decimal | None = Field(default=None, ge=0)
    selected_iterations: int | None = Field(default=None, ge=1)


class MLEvaluationMetrics(FeatureModel):
    model_name: str
    horizon_days: ForecastHorizon
    category: str = "all"
    cohort: ProductCohort = ProductCohort.ALL
    scored_rows: int = Field(ge=0)
    mae: Decimal | None = Field(default=None, ge=0)
    wape_percent: Decimal | None = Field(default=None, ge=0)
    mase: Decimal | None = Field(default=None, ge=0)
    bias_units: Decimal | None = None


class HorizonTrainingResult(FeatureModel):
    horizon_days: ForecastHorizon
    status: ModelSelectionStatus
    reason: str | None = None
    development_rows: int = Field(ge=0)
    embargoed_rows: int = Field(ge=0)
    test_rows: int = Field(ge=0)
    test_start_date: date | None = None
    test_nonoverlapping_origins: int = Field(default=0, ge=0)
    deployment_ineligible_rows: int = Field(default=0, ge=0)
    selected_candidate: str | None = None
    selected_loss_function: str | None = None
    selected_iterations: int | None = Field(default=None, ge=1)
    candidate_results: tuple[CatBoostCandidateResult, ...] = ()
    metrics: tuple[MLEvaluationMetrics, ...] = ()
    model_file: str | None = None
    model_sha256: str | None = None


class CatBoostEvaluationReport(FeatureModel):
    version: Literal["catboost-evaluation-v1"] = "catboost-evaluation-v1"
    generated_at: AwareDatetime
    seller_id: UUID
    scope: EvaluationScope
    catboost_version: str
    python_version: str
    platform: str
    feature_version: str
    feature_schema_sha256: str
    config: CatBoostTrainingConfig
    live_recommendations_enabled: Literal[False] = False
    production_selection_allowed: bool
    lineage_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    results: tuple[HorizonTrainingResult, ...]


class CatBoostModelMetadata(FeatureModel):
    version: Literal["catboost-demand-v1"] = "catboost-demand-v1"
    seller_id: UUID
    horizon_days: ForecastHorizon
    trained_at: AwareDatetime
    training_data_cutoff: AwareDatetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    catboost_version: str
    python_version: str
    platform: str
    feature_version: str
    feature_schema_sha256: str
    encoder_version: str | None = None
    lineage_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    feature_names: tuple[str, ...]
    categorical_features: tuple[str, ...]
    loss_function: str
    parameters: dict[str, int | float | str | bool]
    model_file: str
    model_sha256: str
    training_origin_start: date
    training_origin_end: date
    training_rows: int = Field(ge=1)
    evaluation_scope: EvaluationScope
    holdout_selection_status: ModelSelectionStatus
    live_recommendations_enabled: Literal[False] = False


class MLForecastResult(FeatureModel):
    seller_id: UUID
    product_id: UUID
    forecast_origin: AwareDatetime
    horizon_days: ForecastHorizon
    target_start_date: date
    target_end_date: date
    expected_units: Decimal | None = Field(default=None, ge=0)
    status: MLForecastStatus
    reason: str | None = None
    model_version: str
    model_sha256: str
    feature_version: str
    feature_schema_sha256: str
    prediction_interval: ForecastInterval | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validate_availability(self):
        if (self.status == MLForecastStatus.AVAILABLE) != (
            self.expected_units is not None
        ):
            raise ValueError("Only available forecasts may contain expected units.")
        if self.status != MLForecastStatus.AVAILABLE and not self.reason:
            raise ValueError("Unavailable forecasts require an explicit reason.")
        if self.prediction_interval is not None:
            self.prediction_interval.validate_point(
                self.expected_units, self.forecast_origin, self.target_start_date
            )
        return self
