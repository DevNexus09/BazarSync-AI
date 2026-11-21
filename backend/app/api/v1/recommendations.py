from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from app.core.celery_app import celery_app
from app.core.config import settings
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.dependencies.events import get_dashboard_event_emitter
from app.models.recommendation import Recommendation
from app.models.seller import Seller
from app.schemas.recommendation import (
    RecommendationErrorResponse,
    RecommendationGenerateResponse,
    RecommendationJobResponse,
    RecommendationQueuedResponse,
)
from app.services.recommendation_service import (
    AnalyticsExecutionError,
    CompetitorDataNotFoundError,
    ProductNotFoundError,
    RecommendationNotFoundError,
    RecommendationService,
)
from app.services.dashboard.events import DashboardEventEmitter
from app.services.recommendation_jobs import ERROR_MESSAGES, RecommendationJobs

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.post(
    "/generate/{product_id}",
    response_model=RecommendationQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": RecommendationErrorResponse},
        401: {"model": RecommendationErrorResponse},
        403: {"model": RecommendationErrorResponse},
        404: {"model": RecommendationErrorResponse},
        500: {"model": RecommendationErrorResponse},
    },
)
def generate_recommendation(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    event_emitter: DashboardEventEmitter = Depends(get_dashboard_event_emitter),
    idempotency_key: UUID | None = Header(default=None),
) -> RecommendationQueuedResponse | JSONResponse:
    service = RecommendationService(db, event_emitter=event_emitter)
    try:
        product = service.load_product(current_seller.id, product_id)
        if settings.durable_recommendation_jobs_enabled:
            jobs = RecommendationJobs(db)
            job = jobs.create(current_seller.id, product_id, None, idempotency_key, existing_only=True)
            if job is None:
                scrape_run_id = service.generation_preflight(product)
                job = jobs.create(
                    current_seller.id, product_id, scrape_run_id, idempotency_key,
                )
            if job is None:
                raise ProductNotFoundError("Product not found.")
            jobs.dispatch(job.id)
            return RecommendationQueuedResponse(product_id=product_id, task_id=str(job.id), job_id=job.id)
        scrape_run_id = service.generation_preflight(product)
        evidence_scope = (
            {"kwargs": {"scrape_run_id": str(scrape_run_id)}}
            if scrape_run_id is not None else {}
        )
        task = celery_app.send_task(
            "analytics.generate_ai_recommendation",
            args=[str(product_id), str(current_seller.id)],
            **evidence_scope,
        )
        return RecommendationQueuedResponse(
            success=True,
            status="processing",
            product_id=product_id,
            task_id=task.id,
        )
    except ProductNotFoundError as exc:
        return _error_response(exc)
    except CompetitorDataNotFoundError as exc:
        return _error_response(exc)
    except AnalyticsExecutionError as exc:
        return _error_response(exc)
    except OperationalError:
        db.rollback()
        return JSONResponse(status_code=503, content=RecommendationErrorResponse(
            detail="Recommendation storage is temporarily unavailable. Please try again.",
            error_code="storage_unavailable",
        ).model_dump())


@router.get("/products/{product_id}/job", response_model=RecommendationJobResponse)
def get_latest_recommendation_job(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> RecommendationJobResponse:
    if settings.durable_recommendation_jobs_enabled:
        job = RecommendationJobs(db).latest(current_seller.id, product_id)
        if job is not None:
            return get_recommendation_job(job.id, db, current_seller)
    raise HTTPException(status_code=404, detail="Recommendation job not found.")


@router.get("/jobs/{job_id}", response_model=RecommendationJobResponse)
def get_recommendation_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> RecommendationJobResponse:
    jobs = RecommendationJobs(db)
    job = jobs.status(current_seller.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Recommendation job not found.")
    if job.status in ("PENDING", "RUNNING"):
        jobs.dispatch(job.id)
        job = jobs.status(current_seller.id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Recommendation job not found.")
    recommendation = db.get(Recommendation, job.recommendation_id) if job.recommendation_id else None
    result = (
        RecommendationService(db).read_result(recommendation)
        if recommendation is not None and recommendation.product_id == job.product_id else None
    )
    error_code = job.error_code if job.status == "FAILED" else None
    return RecommendationJobResponse(
        job_id=job.id, product_id=job.product_id, status=job.status, attempts=job.attempts,
        created_at=job.created_at, started_at=job.started_at, completed_at=job.completed_at,
        error_code=error_code, error_message=ERROR_MESSAGES.get(error_code) if error_code else None,
        result=result,
    )


@router.get(
    "/latest/{product_id}",
    response_model=RecommendationGenerateResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": RecommendationErrorResponse},
        401: {"model": RecommendationErrorResponse},
        403: {"model": RecommendationErrorResponse},
        404: {"model": RecommendationErrorResponse},
        500: {"model": RecommendationErrorResponse},
    },
)
def get_latest_recommendation(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> RecommendationGenerateResponse | JSONResponse:
    service = RecommendationService(db)
    try:
        return service.get_latest_recommendation(
            seller_id=current_seller.id,
            product_id=product_id,
        )
    except ProductNotFoundError as exc:
        return _error_response(exc)
    except RecommendationNotFoundError as exc:
        return _error_response(exc)


def _error_response(
    exc: Exception, *, status_code: int | None = None
) -> JSONResponse:
    code = getattr(exc, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR)
    payload = RecommendationErrorResponse(
        success=False,
        detail=getattr(exc, "detail", str(exc)),
        error_code=getattr(exc, "error_code", None),
    ).model_dump()
    return JSONResponse(status_code=status_code or code, content=payload)
