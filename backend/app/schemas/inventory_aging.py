from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.inventory_aging import InventoryAgeSource


class InventoryAgingResponse(BaseModel):
    id: UUID
    seller_id: UUID
    product_id: UUID
    inventory_snapshot_id: UUID | None
    as_of_date: date
    quantity_on_hand: int = Field(..., ge=0)
    quantity_reserved: int = Field(..., ge=0)
    quantity_available: int = Field(..., ge=0)
    eligible_unsold_quantity: int = Field(..., ge=0)
    oldest_age_days: int | None = Field(None, ge=0)
    newest_age_days: int | None = Field(None, ge=0)
    weighted_average_age_days: Decimal | None = Field(None, ge=0)
    age_source: InventoryAgeSource
    is_estimated: bool
    confidence_score: Decimal = Field(..., ge=0, le=100)
    age_buckets: dict[str, Any]
    evidence: dict[str, Any]
    calculation_version: str
    calculated_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LatestInventoryAgingResponse(BaseModel):
    item: InventoryAgingResponse | None
    explanation: str | None = None


class InventoryAgingHistoryResponse(BaseModel):
    items: list[InventoryAgingResponse]
    total: int
    limit: int
    offset: int


class InventoryAgingBucketDistributionResponse(BaseModel):
    product_id: UUID
    age_buckets: dict[str, Any]
