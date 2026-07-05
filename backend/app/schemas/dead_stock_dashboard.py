from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.dead_stock_assessment import (
    DeadStockClassification,
    DeadStockDataStatus,
    DeadStockInventoryAgeState,
    DeadStockRiskLevel,
    DeadStockVisibilityStatus,
)
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction, DeadStockRecoveryRecommendationStatus


class DeadStockSummaryResponse(BaseModel):
    total_products_with_inventory: int
    healthy_product_count: int
    slow_moving_count: int
    at_risk_count: int
    dead_stock_count: int
    critical_risk_count: int
    total_eligible_dead_stock_units: int
    total_locked_capital: Decimal | None
    locked_capital_currency: str | None
    estimated_recoverable_cash: Decimal | None
    recoverable_cash_currency: str | None
    products_with_insufficient_data: int
    products_requiring_manual_review: int
    last_calculation_time: datetime | None
    formula_version: str | None
    monetary_totals_comparable: bool
    forecast_horizon_days: int | None
    age_distribution: dict[str, int]


class DeadStockProductListItem(BaseModel):
    product_id: UUID
    product_name: str
    category: str | None
    current_stock: int
    eligible_unsold_quantity: int | None
    inventory_age_days: int | None
    inventory_age_is_estimated: bool
    age_source: str | None
    days_since_last_sale: int | None
    classification: DeadStockClassification | None
    risk_score: Decimal | None
    risk_level: DeadStockRiskLevel | None
    locked_capital: Decimal | None
    locked_capital_currency: str | None
    primary_recommendation: DeadStockRecoveryAction | None
    recommendation_status: DeadStockRecoveryRecommendationStatus | None
    potential_recovery: Decimal | None
    potential_recovery_low: Decimal | None
    potential_recovery_high: Decimal | None
    data_status: DeadStockDataStatus | None
    last_calculated_at: datetime | None


class DeadStockProductPageResponse(BaseModel):
    items: list[DeadStockProductListItem]
    total: int
    limit: int
    offset: int


class DeadStockProductIntelligenceResponse(BaseModel):
    product_id: UUID
    product_name: str
    category: str | None
    current_inventory: int
    eligible_unsold_quantity: int | None
    inventory_age_days: int | None
    inventory_age_is_estimated: bool
    inventory_age_state: DeadStockInventoryAgeState | None
    age_source: str | None
    days_since_last_sale: int | None
    daily_sales_rate: Decimal | None
    velocity_data_status: str | None
    visibility_status: DeadStockVisibilityStatus | None
    classification: DeadStockClassification | None
    risk_score: Decimal | None
    risk_level: DeadStockRiskLevel | None
    triggered_rules: list[str]
    locked_capital: Decimal | None
    locked_capital_currency: str | None
    primary_recovery_recommendation: DeadStockRecoveryAction | None
    recommended_discount_rate: Decimal | None = Field(None, ge=0, lt=1)
    recommended_price: Decimal | None
    potential_recovered_cash_low: Decimal | None
    potential_recovered_cash: Decimal | None
    potential_recovered_cash_high: Decimal | None
    confidence: Decimal | None
    data_status: DeadStockDataStatus | None
    last_updated_at: datetime | None
    formula_version: str | None
    recovery_recommendation: dict[str, Any] | None
    capital_recovery: dict[str, Any] | None
    evidence: dict[str, Any]
