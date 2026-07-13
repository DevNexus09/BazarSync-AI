from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.sales_data_coverage import SalesDataCompletenessStatus
from app.models.sales_record import SalesRecordStatus

Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2, ge=0)]


class SalesImportRecord(BaseModel):
    product_id: UUID
    quantity: int = Field(gt=0)
    sold_at: datetime
    status: SalesRecordStatus
    unit_price: Money | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    marketplace_listing_id: str | None = Field(default=None, max_length=255)
    is_test_order: bool = False
    source_reference: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("sold_at")
    @classmethod
    def sold_at_not_future(cls, value: datetime) -> datetime:
        candidate = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        if candidate > datetime.now(timezone.utc):
            raise ValueError("sold_at cannot be in the future.")
        return value


class SalesImportRequest(BaseModel):
    records: list[SalesImportRecord] = Field(min_length=1, max_length=100)
    source: str = Field(default="sales_import", min_length=1, max_length=120)
    marketplace: str | None = Field(default=None, max_length=120)
    coverage_start_date: date | None = None
    coverage_end_date: date | None = None
    completeness_status: SalesDataCompletenessStatus = SalesDataCompletenessStatus.UNKNOWN


class SalesImportResponse(BaseModel):
    imported_count: int
    skipped_duplicate_count: int
    valid_sales_count: int
    excluded_sales_count: int
