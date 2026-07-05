from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.sales_record import SalesRecordStatus

Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2, ge=0)]


class SalesImportRecord(BaseModel):
    product_id: UUID
    quantity: int = Field(gt=0)
    sold_at: datetime
    status: SalesRecordStatus
    unit_price: Money | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_test_order: bool = False
    source_reference: str = Field(min_length=1, max_length=255)


class SalesImportRequest(BaseModel):
    records: list[SalesImportRecord] = Field(min_length=1, max_length=100)


class SalesImportResponse(BaseModel):
    imported_count: int
    skipped_duplicate_count: int
    valid_sales_count: int
    excluded_sales_count: int
