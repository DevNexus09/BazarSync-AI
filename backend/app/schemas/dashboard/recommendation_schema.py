from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.dashboard.pagination_schema import PaginatedResponse


class RecommendationSortField(str, Enum):
    created_at = "created_at"
    urgency_score = "urgency_score"
    confidence = "confidence"
    opportunity = "opportunity"


class RecommendationRecord(BaseModel):
    recommendation_id: str
    product_id: str
    product_title: str
    action_type: str
    confidence: str
    urgency_score: float | None = None
    price_gap_percent: float | None = None
    stock_risk_score: float | None = None
    reasoning: str
    revenue_opportunity: float
    created_at: datetime


class RecommendationListResponse(PaginatedResponse[RecommendationRecord]):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "recommendation_id": "5f7d1ac6-2470-4a7b-91b1-447f0f2a60de",
                            "product_id": "1b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                            "product_title": "Dove Body Lotion 200ml",
                            "action_type": "LOWER",
                            "confidence": "HIGH",
                            "urgency_score": 74.0,
                            "price_gap_percent": 7.1,
                            "stock_risk_score": 0.62,
                            "reasoning": "Competitor median price lower and stock risk rising.",
                            "revenue_opportunity": 4200.0,
                            "created_at": "2026-05-26T22:05:00Z",
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
