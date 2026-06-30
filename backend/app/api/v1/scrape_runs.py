from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.scrape import ScrapeRunDetailResponse
from app.services.scrape_service import (
    ScrapeProductNotFoundError,
    ScrapeRunNotFoundError,
    ScrapeService,
)

router = APIRouter(prefix="/scrape-runs", tags=["scrape-runs"])


@router.get("/{scrape_run_id}", response_model=ScrapeRunDetailResponse)
def get_scrape_run_detail(
    scrape_run_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ScrapeRunDetailResponse:
    service = ScrapeService(db)
    try:
        scrape_run, _product = service.get_scrape_run_status(
            seller=current_seller,
            scrape_run_id=scrape_run_id,
        )
    except (ScrapeRunNotFoundError, ScrapeProductNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ScrapeRunDetailResponse(
        id=scrape_run.id,
        product_id=scrape_run.product_id,
        marketplace=scrape_run.marketplace,
        status=scrape_run.status,
        started_at=scrape_run.started_at,
        completed_at=scrape_run.completed_at,
        failed_at=scrape_run.failed_at,
        discovered_competitor_count=scrape_run.discovered_competitor_count,
        snapshot_count=scrape_run.snapshot_count,
        created_at=scrape_run.created_at,
        updated_at=scrape_run.updated_at,
        failure_code=scrape_run.failure_code,
        failure_message="Scrape failed." if scrape_run.status == "FAILED" else None,
    )
