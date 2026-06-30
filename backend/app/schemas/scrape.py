from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.competitor import CompetitorSnapshot, Price


class ScrapeRunResponse(BaseModel):
    success: bool = Field(..., description="Scrape pipeline success flag")
    product_id: UUID = Field(..., description="Seller product ID")
    product_title: str = Field(..., description="Seller product title")
    scrape_run_id: UUID = Field(..., description="Scrape run ID")
    competitors_found: int = Field(..., ge=0, description="Total competitors scraped")
    matched_results: int = Field(..., ge=0, description="Competitors passing similarity threshold")
    filtered_results: int = Field(..., ge=0, description="Competitors filtered out")
    processing_time_seconds: float = Field(..., ge=0, description="Pipeline runtime in seconds")
    competitors: list[CompetitorSnapshot] = Field(default_factory=list)
    scraped_at: datetime | None = Field(None, description="Timestamp of scrape result")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "success": True,
                    "product_id": "1b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                    "product_title": "Dove Body Lotion 200ml",
                    "scrape_run_id": "2b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                    "competitors_found": 8,
                    "matched_results": 5,
                    "filtered_results": 3,
                    "processing_time_seconds": 4.2,
                    "scraped_at": "2026-05-20T10:00:00Z",
                    "competitors": [
                        {
                            "competitor_title": "Dove Nourishing Body Lotion 200ml",
                            "competitor_price": "450.00",
                            "competitor_store": "Official Store",
                            "similarity_score": 0.91,
                            "stock_status": "In Stock",
                            "product_url": "https://www.daraz.com.bd/products/...",
                        }
                    ],
                }
            ]
        }
    )


class ScrapeTaskResponse(BaseModel):
    success: bool = Field(..., description="Enqueue success flag")
    task_id: str = Field(..., description="Celery task ID")
    scrape_run_id: UUID = Field(..., description="Scrape run ID")
    product_id: UUID = Field(..., description="Seller product ID")
    product_title: str = Field(..., description="Seller product title")
    threshold: float = Field(..., ge=0, le=1, description="Similarity threshold used")
    status: str = Field("queued", description="Current task status")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "success": True,
                    "task_id": "8c0f3b0d-1a4a-4a42-b7c6-6519c37b6b1e",
                    "scrape_run_id": "2b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                    "product_id": "1b244d3b-1fbe-4e8c-aea6-47ad97527ac7",
                    "product_title": "Dove Body Lotion 200ml",
                    "threshold": 0.65,
                    "status": "queued",
                }
            ]
        }
    )


class ScrapeRunStatusResponse(BaseModel):
    scrape_run_id: UUID = Field(..., description="Scrape run ID")
    product_id: UUID = Field(..., description="Seller product ID")
    product_title: str = Field(..., description="Seller product title")
    status: str = Field(..., description="Scrape run status")
    started_at: datetime | None = Field(None, description="Scrape run start time")
    finished_at: datetime | None = Field(None, description="Scrape run finish time")
    total_results: int | None = Field(None, description="Total competitors scraped")
    successful_matches: int | None = Field(None, description="Competitors passing similarity threshold")
    error_message: str | None = Field(None, description="Failure reason")


class ScrapeRunSummaryResponse(BaseModel):
    id: UUID
    product_id: UUID
    marketplace: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    discovered_competitor_count: int | None = None
    snapshot_count: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScrapeRunDetailResponse(ScrapeRunSummaryResponse):
    failure_code: str | None = None
    failure_message: str | None = None


class ScrapeRunPageResponse(BaseModel):
    items: list[ScrapeRunSummaryResponse]
    total: int
    limit: int
    offset: int


class CompetitorSnapshotResponse(BaseModel):
    id: UUID
    scrape_run_id: UUID
    product_id: UUID
    competitor_id: UUID
    price: Price | None = None
    currency: str
    rating: Decimal | None = Field(None, ge=0, le=5)
    review_count: int | None = Field(None, ge=0)
    stock_status: str
    captured_at: datetime
    source_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CompetitorSnapshotPageResponse(BaseModel):
    items: list[CompetitorSnapshotResponse]
    total: int
    limit: int
    offset: int


class CompetitorTimelineResponse(CompetitorSnapshotPageResponse):
    product_id: UUID
    competitor_id: UUID


class CompetitorEventResponse(BaseModel):
    id: UUID
    product_id: UUID
    competitor_id: UUID
    scrape_run_id: UUID
    previous_snapshot_id: UUID | None = None
    current_snapshot_id: UUID | None = None
    event_type: str
    old_value: dict | None = None
    new_value: dict | None = None
    price_change_amount: Price | None = None
    price_change_percent: Decimal | None = None
    severity: str
    detected_at: datetime
    metadata: dict | None = Field(None, validation_alias="event_metadata")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CompetitorEventPageResponse(BaseModel):
    items: list[CompetitorEventResponse]
    total: int
    limit: int
    offset: int


class CompetitorRankingResponse(BaseModel):
    id: UUID
    product_id: UUID
    competitor_id: UUID
    scrape_run_id: UUID
    price_score: Decimal
    rating_score: Decimal
    review_score: Decimal
    availability_score: Decimal
    total_score: Decimal
    market_rank: int
    formula_version: str
    calculated_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CompetitorRankingPageResponse(BaseModel):
    items: list[CompetitorRankingResponse]
    total: int
    limit: int
    offset: int


class CompetitorRankingMetadataResponse(BaseModel):
    formula_version: str
    weights: dict[str, Decimal]
    latest_scrape_run_id: UUID | None = None
    ranking_count: int
    last_calculated_at: datetime | None = None


class CompetitorRankingExcludedResponse(BaseModel):
    items: list[dict]
    total: int


class MarketPositionCardResponse(BaseModel):
    seller_product_price: Price | None = None
    lowest_competitor_price: Price | None = None
    highest_competitor_price: Price | None = None
    median_competitor_price: Price | None = None
    strongest_competitor_id: UUID | None = None
    seller_price_difference_from_market_median: Price | None = None
    total_active_competitors: int
    total_in_stock_competitors: int
    ranking_last_updated_at: datetime | None = None
    seller_price_rank: int | None = None


class MarketOpportunityResponse(BaseModel):
    id: UUID
    product_id: UUID
    competitor_id: UUID | None = None
    trigger_event_id: UUID
    scrape_run_id: UUID
    opportunity_type: str
    opportunity_level: str
    opportunity_score: Decimal
    estimated_revenue: Decimal | None = None
    estimated_revenue_currency: str
    recommended_action: str
    explanation: str
    confidence_score: Decimal
    evidence: dict
    status: str
    detected_at: datetime
    expires_at: datetime | None = None
    acknowledged_at: datetime | None = None
    dismissed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MarketOpportunityPageResponse(BaseModel):
    items: list[MarketOpportunityResponse]
    total: int
    limit: int
    offset: int


class CompetitorDashboardSummaryResponse(BaseModel):
    competitor_count: int
    price_drop_count: int
    stockout_count: int
    open_opportunity_count: int
    last_updated_at: datetime | None = None
    window_hours: int
    window_start: datetime
    window_end: datetime
    competitor_count_scope: str
    event_count_scope: str
    opportunity_count_scope: str


class LatestPriceChangeResponse(BaseModel):
    event_type: str
    competitor_id: UUID
    competitor: str | None = None
    product_id: UUID
    product: str | None = None
    old_price: Decimal | None = None
    new_price: Decimal | None = None
    change_amount: Decimal | None = None
    change_percentage: Decimal | None = None
    event_time: datetime
    severity: str


class CompetitorActivityResponse(BaseModel):
    event_type: str
    competitor_id: UUID
    competitor: str | None = None
    product_id: UUID
    product: str | None = None
    description: str
    severity: str
    event_time: datetime
    supporting_values: dict | None = None


class OpportunityFeedResponse(BaseModel):
    id: UUID
    opportunity_level: str
    opportunity_score: Decimal
    estimated_revenue: Decimal | None = None
    estimated_revenue_state: str
    recommended_action: str
    confidence_score: Decimal
    explanation: str
    evidence: dict | None = None
    status: str
    detected_at: datetime


class FeedPageResponse(BaseModel):
    items: list[dict]
    total: int
    limit: int
    offset: int
