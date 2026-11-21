"""Operator-owned model registry and internal forecast routing contracts."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.demand_regime import DemandRegime
from app.schemas.forecast_features import (
    FeatureModel,
    ForecastHorizon,
    ForecastFeatureRow,
)
from app.schemas.statistical_forecast import ForecastResult
from app.schemas.forecast_uncertainty import CalibrationPeriod
from app.services.historical_dataset_service import BUSINESS_TIMEZONE, DAY, _opening

SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Release = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]
ModelSlot = Literal["active", "previous"]


class ForecastMode(StrEnum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    ENABLED = "enabled"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REVOKED = "revoked"


class InferenceFailure(StrEnum):
    REGISTRY_UNAVAILABLE = "registry_unavailable"
    MODEL_INELIGIBLE = "model_ineligible"
    MODEL_NOT_APPROVED = "model_not_approved"
    MODEL_NOT_AVAILABLE_AT_ORIGIN = "model_not_available_at_origin"
    UNSUPPORTED_HORIZON = "unsupported_horizon"
    UNSUPPORTED_VERSION = "unsupported_version"
    FEATURE_SCHEMA_MISMATCH = "feature_schema_mismatch"
    DEPENDENCY_MISMATCH = "dependency_mismatch"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_REJECTED = "artifact_rejected"
    TIMEOUT = "timeout"
    BUSY = "busy"
    WORKER_FAILURE = "worker_failure"


class HoldoutMetrics(FeatureModel):
    scope: Literal["historical_holdout", "synthetic"]
    start_date: date
    end_date: date
    outcome_cutoff: AwareDatetime
    matched_rows: int = Field(ge=1)
    nonoverlapping_origin_dates: int = Field(ge=1)
    mae: Decimal = Field(ge=0)
    baseline_mae: Decimal = Field(ge=0)
    wape_percent: Decimal | None = Field(default=None, ge=0)
    mase: Decimal | None = Field(default=None, ge=0)
    bias_units: Decimal | None = None


class LeadTimeDemandCalibration(FeatureModel):
    """Product-specific upper demand bound evaluated on later, disjoint windows."""

    method: Literal["lead_time_residual_upper_v1"] = "lead_time_residual_upper_v1"
    product_id: UUID
    model_sha256: SHA256
    radius_units: Decimal = Field(ge=1, le=2_147_483_647)
    nominal_level: Decimal = Field(gt=0.5, lt=1)
    calibration: CalibrationPeriod
    validation_first_origin: date
    validation_last_origin: date
    validation_outcomes_available_at: AwareDatetime
    validation_windows: int = Field(ge=20)
    within_upper_bound: int = Field(ge=0)
    validation_lineage_sha256: SHA256

    @model_validator(mode="after")
    def check_validation(self) -> Self:
        if (
            self.within_upper_bound > self.validation_windows
            or self.validation_first_origin > self.validation_last_origin
            or self.calibration.available_at >= _opening(self.validation_first_origin)
            or self.calibration.last_target_date >= self.validation_first_origin
        ):
            raise ValueError(
                "Lead-time bound requires independent chronological validation."
            )
        return self

    @property
    def coverage_lower_bound(self) -> Decimal:
        """One-sided 95% Wilson lower limit on observed holdout coverage."""
        n = Decimal(self.validation_windows)
        p = Decimal(self.within_upper_bound) / n
        z = Decimal("1.644854")
        z2 = z * z
        return (p + z2 / (2 * n) - z * ((p * (1 - p) + z2 / (4 * n)) / n).sqrt()) / (
            1 + z2 / n
        )


class HorizonArtifact(FeatureModel):
    horizon_days: ForecastHorizon
    artifact_sha256: SHA256
    validation: HoldoutMetrics
    reorder_calibrations: tuple[LeadTimeDemandCalibration, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )


class ForecastModelManifest(FeatureModel):
    release: Release
    seller_id: UUID
    model_name: Literal["catboost"] = "catboost"
    model_version: str = Field(min_length=1, max_length=64)
    trained_at: AwareDatetime
    training_data_cutoff: AwareDatetime
    feature_version: str
    feature_schema_sha256: SHA256
    encoder_version: str
    lineage_sha256: SHA256 | None = None
    dependencies: dict[str, str]
    artifacts: tuple[HorizonArtifact, ...] = Field(min_length=1, max_length=3)
    approval_status: ApprovalStatus
    approved_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_approval(self) -> Self:
        if len({item.horizon_days for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("Duplicate supported horizon.")
        if self.training_data_cutoff > self.trained_at:
            raise ValueError("Training data cutoff follows training.")
        if self.approval_status == ApprovalStatus.APPROVED:
            if self.lineage_sha256 is None:
                raise ValueError("Approval requires archived input lineage.")
            if self.approved_at is None or self.approved_at < self.trained_at:
                raise ValueError("Approval must be dated after model training.")
            for artifact in self.artifacts:
                metrics = artifact.validation
                if (
                    metrics.scope != "historical_holdout"
                    or metrics.mae >= metrics.baseline_mae
                    or metrics.matched_rows < 3
                    or not 3
                    <= metrics.nonoverlapping_origin_dates
                    <= metrics.matched_rows
                    or metrics.outcome_cutoff > self.approved_at
                    or metrics.start_date > metrics.end_date
                    or metrics.nonoverlapping_origin_dates
                    > 1
                    + (metrics.end_date - metrics.start_date).days
                    // artifact.horizon_days
                    or self.training_data_cutoff >= _opening(metrics.start_date)
                    or metrics.outcome_cutoff
                    < _opening(metrics.end_date + (artifact.horizon_days + 1) * DAY)
                ):
                    raise ValueError(
                        "Approval requires documented matched historical holdout improvement."
                    )
                calibrations = artifact.reorder_calibrations
                if len({item.product_id for item in calibrations}) != len(calibrations):
                    raise ValueError("Duplicate product lead-time calibrations.")
                for item in calibrations:
                    period = item.calibration
                    first = period.first_origin.astimezone(BUSINESS_TIMEZONE).date()
                    last = period.last_origin.astimezone(BUSINESS_TIMEZONE).date()
                    if (
                        item.model_sha256 != artifact.artifact_sha256
                        or period.last_target_date != last + artifact.horizon_days * DAY
                        or period.available_at < _opening(period.last_target_date + DAY)
                        or period.scored_windows
                        > 1 + (last - first).days // artifact.horizon_days
                        or Decimal(period.scored_windows + 1) * item.nominal_level
                        > period.scored_windows
                        or self.training_data_cutoff >= period.first_origin
                        or item.validation_windows
                        > 1
                        + (
                            item.validation_last_origin - item.validation_first_origin
                        ).days
                        // artifact.horizon_days
                        or not (
                            _opening(
                                item.validation_last_origin
                                + (artifact.horizon_days + 1) * DAY
                            )
                            <= item.validation_outcomes_available_at
                            <= self.approved_at
                        )
                    ):
                        raise ValueError(
                            "Invalid lead-time calibration support or cutoff."
                        )
        return self


class ForecastModelRegistry(FeatureModel):
    version: Literal["forecast-registry-v1"] = "forecast-registry-v1"
    seller_id: UUID
    active: ForecastModelManifest | None = None
    previous: ForecastModelManifest | None = None

    @model_validator(mode="after")
    def check_slots(self) -> Self:
        entries = [entry for entry in (self.active, self.previous) if entry is not None]
        if any(entry.seller_id != self.seller_id for entry in entries):
            raise ValueError("Registry entries must be seller-scoped.")
        if len({entry.release for entry in entries}) != len(entries):
            raise ValueError("Active and previous releases must differ.")
        return self


class InferenceLimits(FeatureModel):
    timeout_seconds: float = Field(default=5, ge=0.05, le=30)
    cpu_seconds: int = Field(default=4, ge=1, le=30)
    address_space_mib: int = Field(default=1024, ge=256, le=4096)
    artifact_mib: int = Field(default=32, ge=1, le=64)
    max_concurrent: int = Field(default=1, ge=1, le=4)


class NativeInferenceRequest(FeatureModel):
    row: ForecastFeatureRow
    slot: ModelSlot
    limits: InferenceLimits


class NativeInferenceReply(FeatureModel):
    units: Decimal | None = Field(default=None, ge=0)
    failure: InferenceFailure | None = None

    @model_validator(mode="after")
    def check_result(self) -> Self:
        if (self.units is None) == (self.failure is None):
            raise ValueError("A worker reply requires exactly one outcome.")
        return self


class InferenceAttempt(FeatureModel):
    slot: ModelSlot
    failure: InferenceFailure | None


class ForecastInferenceResult(FeatureModel):
    mode: ForecastMode
    forecast: ForecastResult
    source: Literal["active", "previous", "baseline", "insufficient_data"]
    shadow_forecast: ForecastResult | None = None
    shadow_source: Literal["active", "previous"] | None = None
    attempts: tuple[InferenceAttempt, ...] = ()
    selection_reason: str
    demand_regime: DemandRegime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    lead_time_calibration: LeadTimeDemandCalibration | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
