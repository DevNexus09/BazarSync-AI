"""Versioned feature and origin snapshot contracts."""

from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from typing import Final, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, ConfigDict, Field

from app.services.historical_dataset_service import HistoricalDataset

ForecastHorizon = Literal[7, 14, 30]
FEATURE_VERSION: Final = "forecast-features-v1"
SNAPSHOT_VERSION: Final = "forecast-source-v1"


class FeatureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class CompetitorPriceObservation(FeatureModel):
    seller_id: UUID
    product_id: UUID
    marketplace: str
    listing: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    price: Decimal = Field(gt=0)
    snapshot_id: UUID
    observed_at: AwareDatetime
    available_at: AwareDatetime


class CatalogSnapshot(FeatureModel):
    seller_id: UUID
    product_id: UUID
    created_at: AwareDatetime
    updated_at: AwareDatetime
    category: str | None = None
    brand: str | None = None
    base_price: Decimal | None = Field(default=None, ge=0)
    currency: Literal["BDT"] = "BDT"
    last_price_change: Decimal | None = None
    price_change_at: AwareDatetime | None = None
    price_change_recorded_at: AwareDatetime | None = None
    price_history_id: UUID | None = None


class ForecastSourceSnapshot(FeatureModel):
    version: Literal["forecast-source-v1"] = SNAPSHOT_VERSION
    captured_at: AwareDatetime
    seller_id: UUID
    product_id: UUID
    history: HistoricalDataset
    catalog: CatalogSnapshot
    competitors: tuple[CompetitorPriceObservation, ...] = ()


class BangladeshHolidayCalendar(FeatureModel):
    version: str = Field(min_length=1)
    source: AnyHttpUrl
    published_at: AwareDatetime
    holidays: dict[date, bool]


class CalendarFeatures(FeatureModel):
    day_of_week: int
    month: int
    weekend: bool
    month_end: bool
    public_holiday: bool | None


class SalesWindow(FeatureModel):
    days: int
    observed_days: int
    total_units: int | None
    population_stddev: Decimal | None
    zero_sales_percent: Decimal | None


class MarketFeatures(FeatureModel):
    marketplace: str
    currency: str
    median_price: Decimal
    listing_count: int
    newest_observation_age_seconds: int
    oldest_observation_age_seconds: int


class ForecastFeatures(FeatureModel):
    sales_lag_1d: int | None
    sales_lag_7d: int | None
    sales_lag_14d: int | None
    sales_lag_28d: int | None
    rolling_7d: SalesWindow
    rolling_14d: SalesWindow
    rolling_30d: SalesWindow
    category: str | None
    brand: str | None
    product_age_days: int
    known_base_price: Decimal | None
    price_currency: str | None
    latest_base_price_change: Decimal | None
    latest_price_change_at: AwareDatetime | None
    feature_calendar: CalendarFeatures
    target_calendar: tuple[CalendarFeatures, ...]
    competitor_markets: tuple[MarketFeatures, ...]
    competitor_price_gap: Decimal | None
    previous_day_on_hand: int | None
    previous_day_stockout: bool | None
    inventory_observed_days_30d: int
    stockout_days_30d: int
    previous_day_promotion: bool | None
    previous_day_discount: Decimal | None


FEATURE_SCHEMA_SHA256 = sha256(
    json.dumps(
        ForecastFeatures.model_json_schema(), sort_keys=True, separators=(",", ":")
    ).encode()
).hexdigest()


class ForecastFeatureQuality(FeatureModel):
    sufficient_history: bool
    usable_sales_days_30d: int
    flags: tuple[str, ...]


class ForecastFeatureRow(FeatureModel):
    version: Literal["forecast-features-v1"] = FEATURE_VERSION
    schema_sha256: str = Field(pattern=f"^{FEATURE_SCHEMA_SHA256}$")
    historical_dataset_version: str
    source_snapshot_version: str
    seller_id: UUID
    product_id: UUID
    feature_date: date
    forecast_origin: AwareDatetime
    data_cutoff: AwareDatetime
    extract_cutoff: AwareDatetime
    horizon_days: ForecastHorizon
    target_start_date: date
    target_end_date: date
    target_name: Literal["total_net_units_sold"] = "total_net_units_sold"
    calendar_versions: tuple[str, ...]
    features: ForecastFeatures
    quality: ForecastFeatureQuality


class ForecastTrainingExample(FeatureModel):
    feature_row: ForecastFeatureRow
    target_net_units: int | None
    eligible_target_days: int
    outcome_extract_cutoff: AwareDatetime
