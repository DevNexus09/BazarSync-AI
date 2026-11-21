from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_serializer
from app.models.recommendation_job import JobStatus

RecommendationAction = Literal["LOWER", "RAISE", "HOLD", "REORDER"]
RecommendationConfidence = Literal["LOW", "MEDIUM", "HIGH"]


class RecommendationAnalyticsResponse(BaseModel):
    stock_coverage_available: bool | None = None
    stock_risk_available: bool | None = None
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

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        payload = handler(self)
        for field in ("stock_coverage_available", "stock_risk_available"):
            if payload.get(field) is None:
                payload.pop(field, None)
        return payload


class RecommendationResponse(BaseModel):
    action: RecommendationAction
    confidence: RecommendationConfidence
    reasoning_bn: str = Field(..., min_length=6)
    revenue_opportunity: float = Field(..., ge=0)


class DashboardForecast(BaseModel):
    horizon_days: Literal[7, 14, 30]
    expected_units: Decimal = Field(ge=0)
    method: str
    version: str
    source: Literal["active", "previous"]
    data_cutoff: datetime
    uncertainty: str
    # Reserved for bounds with validated coverage. The current forecast store
    # supplies empirical, unvalidated intervals and does not populate this.
    prediction_interval: tuple[Decimal, Decimal] | None = None


class DashboardSupportingAction(BaseModel):
    action: str
    source: str


class DashboardPriceCandidate(BaseModel):
    price: Decimal = Field(gt=0)
    constraints_passed: bool
    price_change_eligible: bool | None = None
    rejection_reasons: list[str] = Field(default_factory=list)


class DashboardReorder(BaseModel):
    quantity: int | None = Field(default=None, ge=0)
    deadline: date | None = None
    reorder_point: int | None = Field(default=None, ge=0)
    lead_time_demand: Decimal | None = Field(default=None, ge=0)
    validated_demand_upper_bound: Decimal | None = Field(default=None, ge=0)
    demand_source: Literal["approved_forecast", "recorded_sales_velocity"] | None = None
    uncertainty: str | None = None


class RecommendationDashboardEvidence(BaseModel):
    competitor_observed_at: datetime | None = None
    competitor_freshness: Literal["FRESH", "PARTIAL", "STALE", "UNKNOWN", "UNAVAILABLE"] | None = None
    inventory_observed_at: datetime | None = None
    sales_through: date | None = None
    available_units: int | None = Field(default=None, ge=0)
    daily_sales_rate: Decimal | None = Field(default=None, ge=0)
    sales_rate_observed: bool | None = None
    target_price: Decimal | None = Field(default=None, gt=0)
    reason_codes: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False
    price_blocked: bool = False
    forecasts: list[DashboardForecast] = Field(default_factory=list)
    supporting_actions: list[DashboardSupportingAction] = Field(default_factory=list)
    pricing_candidates: list[DashboardPriceCandidate] = Field(default_factory=list)
    reorder: DashboardReorder | None = None


class RecommendationGenerateResponse(BaseModel):
    success: bool = True
    product_id: UUID
    recommendation: RecommendationResponse
    analytics: RecommendationAnalyticsResponse
    created_at: datetime
    dashboard_evidence: RecommendationDashboardEvidence | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        payload = handler(self)
        if self.dashboard_evidence is None:
            payload.pop("dashboard_evidence", None)
        return payload

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
    job_id: UUID | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        payload = handler(self)
        if self.job_id is None:
            payload.pop("job_id", None)
        return payload

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


class RecommendationJobResponse(BaseModel):
    job_id: UUID
    product_id: UUID
    status: JobStatus
    attempts: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None = None
    error_message: str | None = None
    result: RecommendationGenerateResponse | None = None
