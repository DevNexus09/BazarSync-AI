"""Evidence and seller-scoped selection policies for Task 12."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.forecast_features import FeatureModel, ForecastHorizon
from app.schemas.statistical_forecast import (
    BaselineConfig,
    BaselineModel,
    ForecastResult,
)


class DemandRegime(StrEnum):
    INSUFFICIENT_HISTORY = "insufficient_history"
    INTERMITTENT = "intermittent"
    REGULAR = "regular"
    POTENTIALLY_DECLINING = "potentially_declining"


class DemandRegimeEvidence(FeatureModel):
    regime: DemandRegime
    reason: str
    product_age_days: int = Field(ge=0)
    assessed_days: int = Field(ge=0)
    reliable_days: int = Field(ge=0)
    contiguous_days: int = Field(ge=0)
    stockout_censored_days: int = Field(ge=0)
    missing_dates: int = Field(ge=0)
    other_unreliable_days: int = Field(ge=0)
    nonzero_days: int = Field(ge=0)
    nonzero_frequency: Decimal | None = Field(ge=0, le=1)
    average_demand_interval_days: Decimal | None = Field(gt=0)
    population_variance: Decimal | None = Field(ge=0)
    previous_28_units: int | None = Field(ge=0)
    recent_28_units: int | None = Field(ge=0)


class RegimeModelScore(FeatureModel):
    method: BaselineModel | Literal["historical_mean"]
    scored_rows: int = Field(ge=0)
    mae: Decimal | None = Field(ge=0)


class RegimeRanking(FeatureModel):
    regime: DemandRegime
    horizon_days: ForecastHorizon
    eligible_rows: int = Field(ge=1)
    distinct_origin_dates: int = Field(ge=1)
    nonoverlapping_origin_dates: int = Field(ge=1)
    scores: tuple[RegimeModelScore, ...]
    preferred_methods: tuple[BaselineModel, ...]


class RegimeSelectionPolicy(FeatureModel):
    version: Literal["demand-regime-v1"] = "demand-regime-v1"
    seller_id: UUID
    baseline_config: BaselineConfig
    statsforecast_version: str | None
    statsforecast_dependencies: dict[str, str]
    available_at: AwareDatetime
    first_origin_date: date
    last_origin_date: date
    rankings: tuple[RegimeRanking, ...] = Field(max_length=9)

    @model_validator(mode="after")
    def check_unique_rankings(self) -> Self:
        if len({(entry.regime, entry.horizon_days) for entry in self.rankings}) != len(
            self.rankings
        ):
            raise ValueError("Duplicate regime and horizon ranking.")
        return self


class RegimeForecast(FeatureModel):
    forecast: ForecastResult
    evidence: DemandRegimeEvidence
    selection_version: Literal["demand-regime-v1"] = "demand-regime-v1"
    selection_reason: str
    policy_available_at: AwareDatetime | None = None
    attempted_methods: tuple[BaselineModel, ...] = ()
