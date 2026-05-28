from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.dashboard.pagination_schema import PaginatedResponse


class OpportunitySortField(str, Enum):
    revenue_opportunity = "revenue_opportunity"
    market_opportunity_score = "market_opportunity_score"
    created_at = "created_at"


class OpportunityRecord(BaseModel):
    recommendation_id: str
    product_id: str
    product_title: str
    revenue_opportunity: float
    inventory_capture_units: float
    projected_demand_shift: float
    estimated_profit_impact: float
    competitor_oos_ratio: float
    market_opportunity_score: int
    created_at: datetime


class OpportunityListResponse(PaginatedResponse[OpportunityRecord]):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "recommendation_id": "5f7d1ac6-2470-4a7b-91b1-447f0f2a60de",
                            "product_id": "1b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                            "product_title": "Dove Body Lotion 200ml",
                            "revenue_opportunity": 4200.0,
                            "inventory_capture_units": 12.0,
                            "projected_demand_shift": 18.0,
                            "estimated_profit_impact": 756.0,
                            "competitor_oos_ratio": 0.5,
                            "market_opportunity_score": 71,
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
