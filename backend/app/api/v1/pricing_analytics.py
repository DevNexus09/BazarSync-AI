from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.pricing_analytics import (
    PricingAnalyticsGenerateResponse,
    PricingAnalyticsHistoryResponse,
    PricingAnalyticsLatestResponse,
    PricingAnalyticsWorkflowResponse,
)
from app.services.pricing_analytics_service import PricingAnalyticsService, ProductNotFoundError
from app.services.pricing_calculator import PricingCalculationError
from app.tasks.pricing_analytics_tasks import calculate_pricing_analytics_task

router = APIRouter(tags=["pricing-analytics"])


@router.get("/products/{product_id}/pricing/analytics", response_model=PricingAnalyticsLatestResponse)
def get_latest_pricing_analytics(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> PricingAnalyticsLatestResponse:
    try:
        item = PricingAnalyticsService(db).latest(seller_id=current_seller.id, product_id=product_id)
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.") from exc
    return PricingAnalyticsLatestResponse(item=item)


@router.get("/products/{product_id}/pricing/analytics/history", response_model=PricingAnalyticsHistoryResponse)
def get_pricing_analytics_history(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> PricingAnalyticsHistoryResponse:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date range.")
    try:
        items, total = PricingAnalyticsService(db).history(
            seller_id=current_seller.id,
            product_id=product_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.") from exc
    return PricingAnalyticsHistoryResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/products/{product_id}/pricing/analytics", response_model=PricingAnalyticsGenerateResponse)
def generate_pricing_analytics(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> PricingAnalyticsGenerateResponse:
    try:
        snapshot = PricingAnalyticsService(db).generate_for_product(
            seller_id=current_seller.id,
            product_id=product_id,
        )
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.") from exc
    except (PricingCalculationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return PricingAnalyticsGenerateResponse(
        product_id=product_id,
        snapshot_id=snapshot.id,
        data_status=snapshot.data_status,
        calculation_version=snapshot.calculation_version,
        calculated_at=snapshot.calculated_at,
    )


@router.post("/pricing/analytics/workflow", response_model=PricingAnalyticsWorkflowResponse)
def enqueue_pricing_analytics_workflow(
    current_seller: Seller = Depends(get_current_seller),
    product_id: UUID | None = Query(None),
) -> PricingAnalyticsWorkflowResponse:
    result = calculate_pricing_analytics_task.delay(
        seller_id=str(current_seller.id),
        product_id=str(product_id) if product_id else None,
    )
    return PricingAnalyticsWorkflowResponse(task_id=result.id, seller_id=current_seller.id, product_id=product_id)
