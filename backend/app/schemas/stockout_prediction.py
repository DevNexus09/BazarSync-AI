from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.stockout_prediction import StockoutPredictionStatus


class StockoutPredictionResponse(BaseModel):
    id: UUID
    seller_id: UUID
    product_id: UUID
    inventory_snapshot_id: UUID | None
    sales_velocity_id: UUID | None
    as_of_date: date
    quantity_on_hand: int
    quantity_reserved: int
    quantity_incoming: int
    inventory_position: int
    daily_sales_rate: Decimal
    days_remaining: Decimal
    predicted_stockout_date: date | None
    prediction_status: StockoutPredictionStatus
    confidence_score: Decimal
    calculation_version: str
    calculated_at: datetime
    explanation: str
    calculation_metadata: dict[str, Any] | None = Field(None, alias="metadata")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LatestStockoutPredictionResponse(BaseModel):
    item: StockoutPredictionResponse | None


class StockoutPredictionHistoryResponse(BaseModel):
    items: list[StockoutPredictionResponse]
    total: int
    limit: int
    offset: int
