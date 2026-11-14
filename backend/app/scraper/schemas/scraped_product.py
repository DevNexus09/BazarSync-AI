from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

AcquisitionMethod = Literal["httpx", "playwright_api", "chromium"]
Price = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Count = Annotated[int, Field(ge=0, le=2_147_483_647)]
StockStatus = Literal["IN_STOCK", "OUT_OF_STOCK", "UNKNOWN"]
ExtractionStatus = Literal["SUCCESS", "PARTIAL", "FAILED"]
ExtractionSource = Literal["ajax", "json_ld", "application_json", "html"]
PARSER_VERSION = "2.1"

# Identity is required and independently validated. Optional fields contribute to coverage.
DEFAULT_WEIGHTS = {
    "current_price": 3.0, "seller_name": 2.0, "stock_status": 2.0,
    "rating": 1.0, "review_count": 1.0, "sold_count": 1.0,
    "description": 1.0, "image_url": 1.0, "brand": 1.0, "category": 1.0,
    "specifications": 1.0, "original_price": 1.0, "discount_percentage": 1.0,
}
IMPORTANT_FIELDS = ("current_price", "seller_name", "stock_status")


class ProductFields(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    current_price: Price | None = None
    original_price: Price | None = None
    discount_percentage: int | None = Field(None, ge=0, le=100)
    currency: Literal["BDT"] | None = None
    seller_name: str | None = Field(None, max_length=255)
    rating: float | None = Field(None, ge=0, le=5, allow_inf_nan=False)
    review_count: Count | None = None
    sold_count: Count | None = None
    sold_label: str | None = Field(None, max_length=50)
    stock_status: StockStatus = "UNKNOWN"
    stock_text: str | None = Field(None, max_length=50)
    image_url: str | None = None
    brand: str | None = Field(None, max_length=120)
    category: str | None = Field(None, max_length=120)
    description: str | None = None
    specifications: dict[str, str] = Field(default_factory=dict)
    field_sources: dict[str, ExtractionSource] = Field(default_factory=dict, exclude=True)


class ScrapedProduct(ProductFields):
    title: str = Field(min_length=1, max_length=255)
    product_url: str = Field(min_length=1)
    search_position: int = Field(ge=1)


class ExtractionQuality(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ExtractionStatus
    score: float = Field(ge=0, le=1)
    missing_important: tuple[str, ...] = ()


def validate_weights(weights: dict[str, float]) -> dict[str, float]:
    if (
        not weights or weights.keys() - DEFAULT_WEIGHTS.keys()
        or any(not math.isfinite(weight) or weight <= 0 for weight in weights.values())
    ):
        raise ValueError("Extraction weights require known fields and positive finite values.")
    return weights


def assess_extraction(
    product: ScrapedProduct | None, weights: dict[str, float],
) -> ExtractionQuality:
    if product is None:
        return ExtractionQuality(status="FAILED", score=0)
    missing = tuple(field for field in IMPORTANT_FIELDS if not _present(product, field))
    return ExtractionQuality(
        status="PARTIAL" if missing else "SUCCESS",
        score=round(sum(weight for field, weight in weights.items() if _present(product, field)) / sum(weights.values()), 3),
        missing_important=missing,
    )


def _present(product: ScrapedProduct, field: str) -> bool:
    value = getattr(product, field)
    return value is not None and value != "UNKNOWN" and value != "" and value != {}


class ObservationProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    search_observed_at: datetime
    detail_observed_at: datetime | None = None
    metadata_cached_at: datetime | None = None
    price_observed_at: datetime | None = None
    parser_version: str = PARSER_VERSION
    field_sources: dict[str, ExtractionSource] = Field(default_factory=dict)


@dataclass(frozen=True)
class DetailExtraction:
    fields: ProductFields
    method: AcquisitionMethod | None
    observed_at: datetime
    price_observed_at: datetime | None
    metadata_cached: bool = False

    @classmethod
    def observed(cls, fields: ProductFields, method: AcquisitionMethod) -> Self:
        now = datetime.now(timezone.utc)
        return cls(fields, method, now, now if fields.current_price is not None else None)
