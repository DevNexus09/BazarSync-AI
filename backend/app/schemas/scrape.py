from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.competitor import CompetitorSnapshot


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
