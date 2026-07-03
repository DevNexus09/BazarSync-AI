from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.demand_elasticity_estimate import DemandEstimateDataStatus, DemandEstimationMethod
from app.models.dynamic_pricing_recommendation import DynamicPricingAction


class RevenueSimulationRequest(BaseModel):
    candidate_prices: list[Decimal] = Field(..., min_length=1, max_length=20)
    forecast_horizon_days: int = Field(30, ge=1, le=365)


class RevenueSimulationScenario(BaseModel):
    candidate_price: Decimal
    action: DynamicPricingAction
    is_allowed: bool
    rejection_reasons: list[str]
    expected_units_lower: Decimal | None
    expected_units: Decimal | None
    expected_units_upper: Decimal | None
    expected_revenue: Decimal | None
    expected_profit: Decimal | None
    revenue_impact: Decimal | None
    profit_impact: Decimal | None
    unit_profit: Decimal | None
    margin_rate: Decimal | None
    minimum_safe_price: Decimal | None
    confidence_score: Decimal
    estimation_method: DemandEstimationMethod
    data_status: DemandEstimateDataStatus
    evidence: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class RevenueSimulationResponse(BaseModel):
    seller_id: UUID
    product_id: UUID
    product_title: str
    pricing_analytics_id: UUID
    current_price: Decimal
    baseline_units: Decimal | None
    baseline_expected_revenue: Decimal | None
    baseline_expected_profit: Decimal | None
    forecast_horizon_days: int
    demand_method: DemandEstimationMethod
    data_status: DemandEstimateDataStatus
    confidence_score: Decimal
    calculated_at: datetime
    scenarios: list[RevenueSimulationScenario]
    evidence: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class RevenueSimulationExplanationResponse(BaseModel):
    simulation: RevenueSimulationResponse
    explanation: str
    summary: str
    risks: list[str]
    next_steps: list[str]
    model: str | None = None
