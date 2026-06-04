from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.dependencies.events import get_dashboard_event_emitter
from app.models.seller import Seller
from app.schemas.recommendation import (
    RecommendationErrorResponse,
    RecommendationGenerateResponse,
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
async def generate_recommendation(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    event_emitter: DashboardEventEmitter = Depends(get_dashboard_event_emitter),
) -> RecommendationQueuedResponse | JSONResponse:
    service = RecommendationService(db, event_emitter=event_emitter)
    try:
        product = service.load_product(current_seller.id, product_id)
        competitors = service.load_competitors(current_seller.id, product_id)
        analytics = service.run_analytics(product, competitors)
        service.build_context(product, competitors, analytics)
        task = celery_app.send_task(
            "analytics.generate_ai_recommendation",
            args=[str(product_id), str(current_seller.id)],
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
