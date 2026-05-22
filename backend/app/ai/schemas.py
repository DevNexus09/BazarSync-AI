"""AI recommendation schemas for SMEBoost War Room."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_ACTIONS = Literal["LOWER", "RAISE", "HOLD", "REORDER"]
CONFIDENCE_LABELS = Literal["LOW", "MEDIUM", "HIGH"]


class RecommendationContext(BaseModel):
    """Validated analytics context passed into the LLM prompt system."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sku: str = Field(..., min_length=1, max_length=64)
    product_title: str = Field(..., min_length=1, max_length=120)
    seller_price: float = Field(..., gt=0)
    seller_cost: float = Field(..., ge=0)
    seller_stock: int = Field(..., ge=0)
    competitor_min_price: float | None = Field(default=None, gt=0)
    competitor_median_price: float | None = Field(default=None, gt=0)
    competitors_oos: int = Field(..., ge=0)
    margin_after_fees: float = Field(..., ge=0)
    margin_floor: float = Field(..., ge=0)
    days_of_stock_left: float = Field(..., ge=0)
    supplier_lead_time: int = Field(..., gt=0)
    pricing_pressure_score: float = Field(..., ge=0, le=1)
    stock_risk_score: float = Field(..., ge=0, le=1)
    recommended_action: ALLOWED_ACTIONS
    recommendation_confidence: float = Field(..., ge=0, le=1)


class RecommendationResponse(BaseModel):
    """LLM response after validation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: ALLOWED_ACTIONS
    confidence: CONFIDENCE_LABELS
    reasoning_bn: str = Field(..., min_length=6)
    revenue_opportunity: float = Field(..., ge=0)

    @field_validator("reasoning_bn")
    @classmethod
    def _ensure_bangla_reasoning(cls, value: str) -> str:
        if not _contains_bengali(value):
            raise ValueError("reasoning_bn must contain Bangla characters.")
        return value


class RecommendationMetadata(BaseModel):
    """Operational metadata for observability."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(..., min_length=1)
    latency_ms: int = Field(..., ge=0)
    retry_count: int = Field(..., ge=0)
    generated_at: datetime


class AIModelResponse(BaseModel):
    """Structured response returned by the generator."""

    model_config = ConfigDict(extra="forbid")

    recommendation: RecommendationResponse
    metadata: RecommendationMetadata


def _contains_bengali(text: str) -> bool:
    for char in text:
        if "\u0980" <= char <= "\u09FF":
            return True
    return False
