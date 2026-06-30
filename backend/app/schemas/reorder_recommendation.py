from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.reorder_recommendation import ReorderRecommendationAction, ReorderRecommendationStatus


class ReorderRecommendationResponse(BaseModel):
    id: UUID
    seller_id: UUID
    product_id: UUID
    inventory_snapshot_id: UUID | None
    sales_velocity_id: UUID | None
    stockout_prediction_id: UUID | None
    as_of_date: date
    action: ReorderRecommendationAction
    recommended_quantity: int
    reorder_deadline: date | None
    supplier_lead_time_days: int
    safety_buffer_days: int
    review_period_days: int
    reorder_point: int
    target_stock: int
    inventory_position: int
    daily_sales_rate: Decimal
    confidence_score: Decimal
    recommendation_status: ReorderRecommendationStatus
    explanation: str
    evidence: dict[str, Any]
    calculation_version: str
    generated_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LatestReorderRecommendationResponse(BaseModel):
    item: ReorderRecommendationResponse | None


class ReorderRecommendationHistoryResponse(BaseModel):
    items: list[ReorderRecommendationResponse]
    total: int
    limit: int
    offset: int
