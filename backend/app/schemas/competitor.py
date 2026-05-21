from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Price = Annotated[Decimal, Field(max_digits=12, decimal_places=2, ge=0)]


class CompetitorSnapshot(BaseModel):
    competitor_title: str = Field(..., description="Scraped competitor product title")
    competitor_price: Price | None = Field(None, description="Current competitor price")
    competitor_store: str | None = Field(None, description="Competitor store name")
    similarity_score: float | None = Field(None, ge=0, le=1, description="Similarity score")
    stock_status: str | None = Field(None, description="Stock availability label")
    product_url: str | None = Field(None, description="Competitor product URL")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "competitor_title": "Dove Nourishing Body Lotion 200ml",
                    "competitor_price": "450.00",
                    "competitor_store": "Official Store",
                    "similarity_score": 0.91,
                    "stock_status": "In Stock",
                    "product_url": "https://www.daraz.com.bd/products/...",
                }
            ]
        }
    )


class CompetitorResponse(BaseModel):
    id: UUID
    product_id: UUID
    scrape_run_id: UUID
    competitor_title: str
    competitor_description: str | None = Field(
        None, description="Competitor product description"
    )
    competitor_category: str | None = Field(None, description="Competitor category")
    competitor_brand: str | None = Field(None, description="Competitor brand")
    competitor_attributes: dict[str, str] | None = Field(
        None, description="Structured competitor specifications"
    )
    competitor_price: Price | None = Field(None, description="Current competitor price")
    competitor_rating: float | None = Field(
        None, ge=0, le=5, description="Average competitor rating"
    )
    competitor_sold: str | None = Field(None, description="Sold count label")
    stock_status: str | None = Field(None, description="Stock availability label")
    similarity_score: float | None = Field(None, ge=0, le=1, description="Similarity score")
    title_similarity: float | None = Field(None, ge=0, le=1, description="Title similarity")
    description_similarity: float | None = Field(
        None, ge=0, le=1, description="Description similarity"
    )
    attribute_similarity: float | None = Field(
        None, ge=0, le=1, description="Attribute similarity"
    )
    keyword_score: float | None = Field(None, ge=0, le=1, description="Keyword overlap score")
    ranking_score: float | None = Field(None, ge=0, le=1, description="Ranking score")
    match_confidence: float | None = Field(None, ge=0, le=1, description="Match confidence")
    category_match: bool | None = Field(None, description="Category match flag")
    matched_attributes: list[str] | None = Field(
        None, description="Matched attribute keys"
    )
    competitor_store: str | None = Field(None, description="Competitor store name")
    product_url: str | None = Field(None, description="Competitor product URL")
    marketplace: str = Field(..., description="Marketplace name")
    marketplace_position: int | None = Field(
        None, ge=1, description="Marketplace search position"
    )
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "15ed1ac6-2470-4a7b-91b1-447f0f2a60de",
                    "product_id": "1b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                    "scrape_run_id": "2b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                    "competitor_title": "Dove Nourishing Body Lotion 200ml",
                    "competitor_description": "Hydrating body lotion for dry skin.",
                    "competitor_category": "Cosmetics",
                    "competitor_brand": "Dove",
                    "competitor_attributes": {"volume": "200ml", "skin_type": "dry"},
                    "competitor_price": "450.00",
                    "competitor_rating": 4.6,
                    "competitor_sold": "1.2k",
                    "stock_status": "In Stock",
                    "similarity_score": 0.91,
                    "title_similarity": 0.92,
                    "description_similarity": 0.88,
                    "attribute_similarity": 0.9,
                    "keyword_score": 0.76,
                    "ranking_score": 0.64,
                    "match_confidence": 0.9,
                    "category_match": True,
                    "matched_attributes": ["volume", "skin_type"],
                    "competitor_store": "Official Store",
                    "product_url": "https://www.daraz.com.bd/products/...",
                    "marketplace": "Daraz Bangladesh",
                    "marketplace_position": 3,
                    "created_at": "2026-05-20T10:00:00Z",
                }
            ]
        },
    )


class CompetitorListResponse(BaseModel):
    items: list[CompetitorResponse]
    total: int
    limit: int
    offset: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "id": "15ed1ac6-2470-4a7b-91b1-447f0f2a60de",
                            "product_id": "1b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                            "scrape_run_id": "2b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                            "competitor_title": "Dove Nourishing Body Lotion 200ml",
                            "competitor_price": "450.00",
                            "competitor_rating": 4.6,
                            "competitor_sold": "1.2k",
                            "stock_status": "In Stock",
                            "similarity_score": 0.91,
                            "competitor_store": "Official Store",
                            "product_url": "https://www.daraz.com.bd/products/...",
                            "marketplace": "Daraz Bangladesh",
                            "marketplace_position": 3,
                            "created_at": "2026-05-20T10:00:00Z",
                        }
                    ],
                    "total": 1,
                    "limit": 20,
                    "offset": 0,
                }
            ]
        }
    )
