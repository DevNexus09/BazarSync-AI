from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.sales_velocity import SalesVelocityDataStatus


class SalesVelocityResponse(BaseModel):
    id: UUID
    seller_id: UUID
    product_id: UUID
    as_of_date: date
    window_days: int
    observed_days: int
    gross_units_sold: int
    returned_units: int
    net_units_sold: int
    daily_sales_rate: Decimal
    sales_days: int
    confidence_score: Decimal
    data_status: SalesVelocityDataStatus
    calculation_version: str
    calculated_at: datetime
    calculation_metadata: dict[str, Any] | None = Field(None, alias="metadata")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LatestSalesVelocityResponse(BaseModel):
    item: SalesVelocityResponse | None


class SalesVelocityHistoryResponse(BaseModel):
    items: list[SalesVelocityResponse]
    total: int
    limit: int
    offset: int
