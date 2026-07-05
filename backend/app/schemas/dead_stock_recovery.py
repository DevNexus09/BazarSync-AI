from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.dead_stock_recovery_recommendation import (
    DeadStockRecoveryAction,
    DeadStockRecoveryRecommendationStatus,
)


class DeadStockRecoveryRecommendationResponse(BaseModel):
    id: UUID
    seller_id: UUID
    product_id: UUID
    dead_stock_assessment_id: UUID
    primary_action: DeadStockRecoveryAction
    secondary_actions: list[str]
    recommended_discount_rate: Decimal | None = Field(None, ge=0, lt=1)
    recommended_price: Decimal | None = Field(None, ge=0)
    suggested_duration_days: int | None = Field(None, gt=0)
    recommended_quantity: int | None = Field(None, ge=0)
    confidence_score: Decimal = Field(..., ge=0, le=100)
    recommendation_status: DeadStockRecoveryRecommendationStatus
    explanation: str
    evidence: dict[str, Any]
    rejected_actions: list[dict[str, Any]]
    calculation_version: str
    generated_at: datetime
    expires_at: datetime | None
    acknowledged_at: datetime | None
    dismissed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LatestDeadStockRecoveryRecommendationResponse(BaseModel):
    item: DeadStockRecoveryRecommendationResponse | None


class DeadStockRecoveryRecommendationPageResponse(BaseModel):
    items: list[DeadStockRecoveryRecommendationResponse]
    total: int
    limit: int
    offset: int
