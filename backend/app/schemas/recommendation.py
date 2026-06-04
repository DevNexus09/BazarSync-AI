from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RecommendationAction = Literal["LOWER", "RAISE", "HOLD", "REORDER"]
RecommendationConfidence = Literal["LOW", "MEDIUM", "HIGH"]


class RecommendationAnalyticsResponse(BaseModel):
    competitor_median_price: float | None = Field(
        None, description="Median competitor price for the latest scrape run"
    )
    price_gap_percent: float | None = Field(
        None, description="Seller price gap vs competitor median (%)"
    )
    competitors_oos: int | None = Field(
        None, ge=0, description="Out-of-stock competitors in latest scrape"
    )
    stock_risk_score: float = Field(..., ge=0, le=1)
    pricing_pressure_score: float = Field(..., ge=0, le=1)
    estimated_days_of_stock_left: float = Field(..., ge=0)


class RecommendationResponse(BaseModel):
    action: RecommendationAction
    confidence: RecommendationConfidence
    reasoning_bn: str = Field(..., min_length=6)
    revenue_opportunity: float = Field(..., ge=0)


class RecommendationGenerateResponse(BaseModel):
    success: bool = True
    product_id: UUID
    recommendation: RecommendationResponse
    analytics: RecommendationAnalyticsResponse
    created_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "success": True,
                    "product_id": "1b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                    "recommendation": {
                        "action": "LOWER",
                        "confidence": "HIGH",
                        "reasoning_bn": "Competitor median price আপনার দামের চেয়ে কম...",
                        "revenue_opportunity": 4200,
                    },
                    "analytics": {
                        "competitor_median_price": 435,
                        "price_gap_percent": 8.4,
                        "competitors_oos": 2,
                        "stock_risk_score": 0.62,
                        "pricing_pressure_score": 0.75,
                        "estimated_days_of_stock_left": 6,
                    },
                    "created_at": "2026-05-22T00:00:00Z",
                }
            ]
        }
    )


class RecommendationQueuedResponse(BaseModel):
    success: bool = True
    status: Literal["processing"] = "processing"
    product_id: UUID
    task_id: str

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "success": True,
                    "status": "processing",
                    "product_id": "1b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                    "task_id": "3aa4b1c1-1e7f-4c5e-9f6a-2b7c4b0b6d8a",
                }
            ]
        }
    )


class RecommendationErrorResponse(BaseModel):
    success: bool = False
    detail: str
    error_code: str | None = None
