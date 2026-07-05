from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2, ge=0)]


class InventoryStockInCreate(BaseModel):
    product_id: UUID
    quantity: int = Field(gt=0)
    received_at: datetime
    unit_cost: Money | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    source_reference: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class InventoryStockInResponse(BaseModel):
    id: UUID
    product_id: UUID
    quantity: int
    received_at: datetime
    unit_cost: Decimal | None
    currency: str | None
    source_reference: str | None
    notes: str | None
    age_source_available: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
