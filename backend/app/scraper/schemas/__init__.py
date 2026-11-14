from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.scraper.schemas.scraped_product import AcquisitionMethod as AcquisitionMethod
from app.scraper.schemas.scraped_product import ExtractionQuality, ObservationProvenance, Price


class CompetitorProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_title: str = Field(default="")
    product_description: str = Field(default="")
    product_category: str = Field(default="")
    product_brand: str = Field(default="")
    product_attributes: dict[str, str] = Field(default_factory=dict)
    product_price: Price | None = None
    original_price: Price | None = None
    discount_percentage: int | None = Field(default=None, ge=0, le=100)
    store_name: str = Field(default="")
    rating: float | None = Field(default=None, ge=0, le=5)
    rating_count: int | None = Field(default=None, ge=0, le=2_147_483_647)
    sold_count: str | None = Field(default=None, max_length=50)
    stock_status: str = Field(default="")
    daraz_product_url: str = Field(default="")
    product_image_url: str = Field(default="")
    search_position: int = Field(ge=1)
    ranking_score: float = Field(default=0)
    extraction_quality: ExtractionQuality | None = Field(default=None, exclude=True)
    provenance: ObservationProvenance | None = Field(default=None, exclude=True)
    detail_acquisition_method: AcquisitionMethod | None = Field(default=None, exclude=True)

    @field_serializer("product_price", "original_price", when_used="json")
    def serialize_price(self, value: Price | None) -> float | None:
        return float(value) if value is not None else None



class ScrapeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    marketplace: str
    scraped_at: datetime
    total_results: int = Field(ge=0)
    search_acquisition_method: AcquisitionMethod | None = Field(default=None, exclude=True)
    raw_listing_count: int | None = Field(default=None, exclude=True)
    validated_listing_count: int | None = Field(default=None, exclude=True)
    products: list[CompetitorProduct] = Field(default_factory=list)
