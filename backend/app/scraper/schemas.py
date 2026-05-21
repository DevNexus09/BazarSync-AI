from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class CompetitorProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_title: str = Field(default="")
    product_description: str = Field(default="")
    product_category: str = Field(default="")
    product_brand: str = Field(default="")
    product_attributes: dict[str, str] = Field(default_factory=dict)
    product_price: float = Field(default=0)
    original_price: float = Field(default=0)
    discount_percentage: int = Field(default=0)
    store_name: str = Field(default="")
    rating: float = Field(default=0)
    rating_count: int = Field(default=0)
    sold_count: str = Field(default="")
    stock_status: str = Field(default="")
    daraz_product_url: str = Field(default="")
    product_image_url: str = Field(default="")
    search_position: int = Field(ge=1)
    ranking_score: float = Field(default=0)


class ScrapeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    marketplace: str
    scraped_at: datetime
    total_results: int = Field(ge=0)
    products: list[CompetitorProduct] = Field(default_factory=list)
