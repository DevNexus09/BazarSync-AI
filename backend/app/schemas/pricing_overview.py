from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from app.models.dynamic_pricing_recommendation import DynamicPricingAction, DynamicPricingRecommendationStatus
from app.models.pricing_analytics_snapshot import PricingAnalyticsDataStatus


class MarketPosition(str, Enum):
    ABOVE_MARKET = "ABOVE_MARKET"
    AT_MARKET = "AT_MARKET"
    BELOW_MARKET = "BELOW_MARKET"
    NO_MARKET_DATA = "NO_MARKET_DATA"


class PricingOverviewRecommendation(BaseModel):
    id: UUID
    action: DynamicPricingAction
    recommended_price: Decimal
    recommendation_status: DynamicPricingRecommendationStatus
    confidence_score: Decimal
    profit_impact: Decimal | None
    generated_at: datetime
    expires_at: datetime | None
    is_actionable: bool


class PricingOverviewRow(BaseModel):
    product_id: UUID
    title: str
    sku: str | None
    category: str | None
    current_price: Decimal
    currency: str = "BDT"
    analytics_id: UUID | None
    analytics_calculated_at: datetime | None
    data_status: PricingAnalyticsDataStatus | None
    market_median_price: Decimal | None
    competitor_count: int
    price_vs_median_rate: Decimal | None
    position: MarketPosition
    minimum_safe_price: Decimal | None
    margin_at_risk: bool
    has_pricing_policy: bool
    recommendation: PricingOverviewRecommendation | None


class PricingOverviewSummary(BaseModel):
    product_count: int
    priced_above_market: int
    priced_below_market: int
    margin_at_risk: int
    recommendations_waiting: int
    without_analytics: int
    products_with_pricing_policy: int
    products_with_competitor_data: int
    last_calculated_at: datetime | None
    position_tolerance_rate: Decimal


class PricingOverviewResponse(BaseModel):
    items: list[PricingOverviewRow]
    total: int
    limit: int
    offset: int
    summary: PricingOverviewSummary
