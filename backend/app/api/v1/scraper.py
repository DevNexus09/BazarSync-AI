from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.scraper.exceptions import ScraperError
from app.scraper.schemas import ScrapeResponse
from app.scraper.services.competitor_service import scrape_daraz_competitors
from app.core.celery_app import celery_app
from app.scraper.constants import SIMILARITY_THRESHOLD
from app.schemas.scrape import ScrapeRunStatusResponse, ScrapeTaskResponse
from app.services.scrape_service import (
    ProductAccessError,
    ScrapeProductNotFoundError,
    ScrapeRunNotFoundError,
    ScrapeService,
)

router = APIRouter(prefix="/scraper", tags=["scraper"])


class DarazScrapeRequest(BaseModel):
    product_title: str = Field(..., min_length=2, max_length=200)


@router.post("/daraz", response_model=ScrapeResponse)
async def scrape_daraz(payload: DarazScrapeRequest) -> ScrapeResponse:
    try:
        return await scrape_daraz_competitors(
            product_title=payload.product_title,
        )
    except ScraperError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post("/run/{product_id}", response_model=ScrapeTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_scrape(
    product_id: UUID = Path(..., description="Seller product ID"),
    threshold: float = Query(SIMILARITY_THRESHOLD, ge=0, le=1, description="Similarity threshold"),
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ScrapeTaskResponse:
    service = ScrapeService(db)
    try:
        scrape_run, product = service.create_pending_run(
            seller=current_seller,
            product_id=product_id,
        )
        try:
            task = celery_app.send_task(
                "scraper.run_manual_scrape",
                args=[str(product.id), str(current_seller.id), str(scrape_run.id), threshold],
            )
            return ScrapeTaskResponse(
                success=True,
                task_id=task.id,
                scrape_run_id=scrape_run.id,
                product_id=product.id,
                product_title=product.title,
                threshold=threshold,
                status="queued",
            )
        except Exception as exc:
            service.mark_run_failed(scrape_run.id, str(exc))
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
        error_message=scrape_run.error_message,
    )
