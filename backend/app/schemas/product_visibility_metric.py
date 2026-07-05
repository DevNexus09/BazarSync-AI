from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Rate = Annotated[Decimal, Field(ge=0, le=1)]
Score = Annotated[Decimal, Field(ge=0, le=100)]


class ProductVisibilityMetricCreate(BaseModel):
    marketplace: str = Field(default="DARAZ", min_length=1, max_length=120)
    metric_date: date
    impressions: int = Field(ge=0)
    views: int = Field(ge=0)
    clicks: int = Field(ge=0)
    search_rank: int | None = Field(default=None, gt=0)
    listing_quality_score: Score | None = None
    conversion_rate: Rate | None = None
    source: str = Field(default="manual", min_length=1, max_length=120)
    source_reference: str | None = Field(default=None, max_length=255)


class ProductVisibilityMetricResponse(ProductVisibilityMetricCreate):
    id: UUID
    seller_id: UUID
    product_id: UUID
    visibility_status: str
    visibility_score: Decimal | None
    seo_recommendation_available: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductVisibilityMetricHistoryResponse(BaseModel):
    items: list[ProductVisibilityMetricResponse]
    total: int
    limit: int
    offset: int
