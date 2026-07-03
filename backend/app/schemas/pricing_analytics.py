from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.pricing_analytics_snapshot import PricingAnalyticsDataStatus


class PricingAnalyticsSnapshotResponse(BaseModel):
    id: UUID
    seller_id: UUID
    product_id: UUID
    competitor_scrape_run_id: UUID | None
    inventory_snapshot_id: UUID | None
    sales_velocity_id: UUID | None
    fee_policy_id: UUID | None
    current_price: Decimal
    unit_cost: Decimal
    percentage_fee_rate: Decimal
    fixed_fee_amount: Decimal
    current_unit_profit: Decimal
    current_margin_rate: Decimal | None
    minimum_safe_price: Decimal
    competitor_min_price: Decimal | None
    competitor_q1_price: Decimal | None
    competitor_mean_price: Decimal | None
    competitor_median_price: Decimal | None
    competitor_q3_price: Decimal | None
    competitor_max_price: Decimal | None
    weighted_market_price: Decimal | None
    seller_price_difference_from_median: Decimal | None
    seller_price_percentile: Decimal | None
    competitor_count: int
    in_stock_competitor_count: int
    inventory_position: int | None
    inventory_risk_level: str | None
    daily_sales_rate: Decimal | None
    recent_net_sales: int | None
    product_age_days: int | None
    promotion_state: str | None
    demand_score: Decimal | None
    demand_data_status: PricingAnalyticsDataStatus
    data_status: PricingAnalyticsDataStatus
    confidence_score: Decimal
    evidence: dict[str, Any]
    calculation_version: str
    calculated_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PricingAnalyticsLatestResponse(BaseModel):
    item: PricingAnalyticsSnapshotResponse | None


class PricingAnalyticsHistoryResponse(BaseModel):
    items: list[PricingAnalyticsSnapshotResponse]
    total: int
    limit: int
    offset: int


class PricingAnalyticsGenerateResponse(BaseModel):
    product_id: UUID
    snapshot_id: UUID
    data_status: PricingAnalyticsDataStatus
    calculation_version: str
    calculated_at: datetime


class PricingAnalyticsWorkflowResponse(BaseModel):
    task_id: str | None
    seller_id: UUID
    product_id: UUID | None = None
