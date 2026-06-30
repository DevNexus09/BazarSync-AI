from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.inventory_history import InventorySnapshotSource


class InventoryHistoryResponse(BaseModel):
    id: UUID
    seller_id: UUID
    product_id: UUID
    snapshot_date: date
    captured_at: datetime
    quantity_on_hand: int = Field(..., ge=0)
    quantity_reserved: int = Field(..., ge=0)
    quantity_available: int
    quantity_incoming: int = Field(..., ge=0)
    source: InventorySnapshotSource
    source_reference: str | None
    content_hash: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InventoryHistoryPageResponse(BaseModel):
    items: list[InventoryHistoryResponse]
    total: int
    limit: int
    offset: int


class LatestInventoryHistoryResponse(BaseModel):
    item: InventoryHistoryResponse | None
