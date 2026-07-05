from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.dead_stock_assessment import (
    DeadStockClassification,
    DeadStockDataStatus,
    DeadStockInventoryAgeState,
    DeadStockNoSalesState,
    DeadStockRiskLevel,
    DeadStockVisibilityStatus,
)


class DeadStockAssessmentResponse(BaseModel):
    id: UUID
    seller_id: UUID
    product_id: UUID
    inventory_aging_id: UUID | None
    inventory_snapshot_id: UUID | None
    sales_velocity_id: UUID | None
    as_of_date: date
    classification: DeadStockClassification
    eligible_quantity: int = Field(..., ge=0)
    days_since_last_sale: int | None = Field(None, ge=0)
    last_sale_at: datetime | None
    inventory_age_days: int | None = Field(None, ge=0)
    inventory_age_is_estimated: bool
    no_sales_state: DeadStockNoSalesState
    inventory_age_state: DeadStockInventoryAgeState
    visibility_score: Decimal | None = Field(None, ge=0, le=100)
    visibility_status: DeadStockVisibilityStatus
    risk_score: Decimal = Field(..., ge=0, le=100)
    risk_level: DeadStockRiskLevel
    component_scores: dict[str, Any]
    rule_results: dict[str, Any]
    triggered_rules: list[str]
    data_status: DeadStockDataStatus
    confidence_score: Decimal = Field(..., ge=0, le=100)
    formula_version: str
    explanation: str
    calculation_version: str
    assessed_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LatestDeadStockAssessmentResponse(BaseModel):
    item: DeadStockAssessmentResponse | None


class DeadStockAssessmentPageResponse(BaseModel):
    items: list[DeadStockAssessmentResponse]
    total: int
    limit: int
    offset: int
