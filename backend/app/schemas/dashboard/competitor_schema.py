from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.dashboard.pagination_schema import PaginatedResponse


class CompetitorSortField(str, Enum):
    created_at = "created_at"
    price_gap = "price_gap"
    ranking_position = "ranking_position"
    similarity_score = "similarity_score"
    competitor_price = "competitor_price"


class CompetitorRecord(BaseModel):
    competitor_id: str
    product_id: str
    product_title: str
    competitor_title: str
    competitor_store: str | None = None
    competitor_price: float | None = None
    seller_price: float | None = None
    price_gap_percent: float | None = None
    stock_status: str | None = None
    out_of_stock: bool
    ranking_position: int | None = None
    similarity_score: float | None = None
    marketplace: str
    product_url: str | None = None
    price_trend: str
    created_at: datetime


class CompetitorListResponse(PaginatedResponse[CompetitorRecord]):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "competitor_id": "15ed1ac6-2470-4a7b-91b1-447f0f2a60de",
                            "product_id": "1b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                            "product_title": "Dove Body Lotion 200ml",
                            "competitor_title": "Dove Body Lotion 200ml",
                            "competitor_store": "Official Store",
                            "competitor_price": 420.0,
                            "seller_price": 450.0,
                            "price_gap_percent": 7.14,
                            "stock_status": "out_of_stock",
                            "out_of_stock": True,
                            "ranking_position": 3,
                            "similarity_score": 0.91,
                            "marketplace": "Daraz Bangladesh",
                            "product_url": "https://www.daraz.com.bd/products/...",
                            "price_trend": "down",
                            "created_at": "2026-05-26T22:00:00Z",
                        }
                    ],
                    "meta": {
                        "total": 1,
                        "page": 1,
                        "page_size": 20,
                        "total_pages": 1,
                        "has_next": False,
                        "has_prev": False,
                    },
                }
            ]
        }
    )
