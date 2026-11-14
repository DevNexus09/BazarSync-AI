from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.scraper.exceptions import public_failure_message
from app.scraper.constants import SIMILARITY_THRESHOLD
from app.schemas.scrape import ScrapeRunDetailResponse, ScrapeRunStatusResponse, ScrapeTaskResponse
from app.services.scrape_service import (
    ProductAccessError,
    ScrapeEnqueueError,
    ScrapeProductNotFoundError,
    ScrapeRunNotFoundError,
    ScrapeService,
)

router = APIRouter(prefix="/scraper", tags=["scraper"])


@router.post("/daraz", deprecated=True, status_code=status.HTTP_410_GONE)
def scrape_daraz() -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Use POST /api/v1/scraper/run/{product_id} with an authenticated seller account.",
    )


@router.post("/run/{product_id}", response_model=ScrapeTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def run_scrape(
    product_id: UUID = Path(..., description="Seller product ID"),
    threshold: float = Query(SIMILARITY_THRESHOLD, ge=0, le=1, description="Similarity threshold"),
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ScrapeTaskResponse:
    service = ScrapeService(db)
    try:
        scrape_run, product, _ = service.enqueue_scrape(
            seller_id=current_seller.id,
            product_id=product_id,
            threshold=threshold,
        )
        return ScrapeTaskResponse(
            success=True,
            task_id=scrape_run.celery_task_id,
            scrape_run_id=scrape_run.id,
            product_id=product.id,
            product_title=product.title,
            threshold=service.run_threshold(scrape_run),
            status="queued",
        )
    except ScrapeEnqueueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue scraper task.",
        ) from exc
    except ScrapeProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProductAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ScrapeRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/runs/{scrape_run_id}", response_model=ScrapeRunStatusResponse)
def get_scrape_run_status(
    scrape_run_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ScrapeRunStatusResponse:
    service = ScrapeService(db)
    try:
        scrape_run, product = service.get_scrape_run_status(
            seller=current_seller,
            scrape_run_id=scrape_run_id,
        )
    except (ScrapeRunNotFoundError, ScrapeProductNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ScrapeRunStatusResponse(
        scrape_run_id=scrape_run.id,
        product_id=product.id,
        product_title=product.title,
        status=scrape_run.status,
        started_at=scrape_run.started_at,
        finished_at=scrape_run.finished_at,
        total_results=scrape_run.total_results,
        successful_matches=scrape_run.successful_matches,
        error_message=public_failure_message(scrape_run.failure_code)
        if scrape_run.status == "FAILED" else None,
    )


@router.get("/scrape-runs/{scrape_run_id}", response_model=ScrapeRunDetailResponse)
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
