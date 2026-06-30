from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.inventory_risk import InventoryRiskDataStatus, InventoryRiskLevel


class InventoryRiskResponse(BaseModel):
    id: UUID
    seller_id: UUID
    product_id: UUID
    stockout_prediction_id: UUID | None
    reorder_recommendation_id: UUID | None
    as_of_date: date
    risk_score: Decimal
    risk_level: InventoryRiskLevel | None
    coverage_gap_days: Decimal | None
    data_status: InventoryRiskDataStatus
    confidence_score: Decimal
    factors: dict[str, Any]
    calculation_version: str
    assessed_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LatestInventoryRiskResponse(BaseModel):
    item: InventoryRiskResponse | None


class InventoryRiskPageResponse(BaseModel):
    items: list[InventoryRiskResponse]
    total: int
    limit: int
    offset: int
