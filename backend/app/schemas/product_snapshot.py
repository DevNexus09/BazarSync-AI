from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProductSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID


class ProductSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seller_id: UUID
    product_id: UUID
    product_name: str
    current_price: float
    current_stock: int
    supplier_lead_time: int | None = None
    competitor_median_price: float | None = None
    price_gap_percent: float | None = None
    recommendation_action: str
    ai_reason: str
    confidence: str
    updated_at: datetime
    currency: str = Field(default="৳", min_length=1)


class ProductSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool = True
    message: str
    sent_at: datetime | None = None
    delivery_status: str | None = None


class ProductSnapshotErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool = False
    detail: str
    error_code: str | None = None
