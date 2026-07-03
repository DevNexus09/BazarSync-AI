from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.demand_elasticity_estimate import DemandEstimationMethod
from app.models.dynamic_pricing_recommendation import DynamicPricingAction, DynamicPricingRecommendationStatus
from app.models.pricing_policy import PricingObjective


class DynamicPricingRecommendationResponse(BaseModel):
    id: UUID
    seller_id: UUID
    product_id: UUID
    pricing_analytics_id: UUID
    elasticity_estimate_id: UUID | None
    action: DynamicPricingAction
    current_price: Decimal
    recommended_price: Decimal
    minimum_safe_price: Decimal | None
    expected_units: Decimal | None
    expected_revenue: Decimal | None
    expected_profit: Decimal | None
    baseline_expected_revenue: Decimal | None
    baseline_expected_profit: Decimal | None
    revenue_impact: Decimal | None
    profit_impact: Decimal | None
    margin_rate: Decimal | None
    confidence_score: Decimal
    estimation_method: DemandEstimationMethod
    recommendation_status: DynamicPricingRecommendationStatus
    objective: PricingObjective
    evidence: dict[str, Any]
    formula_version: str
    generated_at: datetime
    expires_at: datetime | None
    acknowledged_at: datetime | None
    dismissed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DynamicPricingRecommendationPageResponse(BaseModel):
    items: list[DynamicPricingRecommendationResponse]
    total: int
    limit: int
    offset: int


class DynamicPricingLatestResponse(BaseModel):
    item: DynamicPricingRecommendationResponse | None
