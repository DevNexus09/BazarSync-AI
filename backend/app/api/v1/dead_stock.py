from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.dead_stock_assessment import DeadStockClassification, DeadStockDataStatus, DeadStockVisibilityStatus
from app.models.seller import Seller
from app.schemas.dead_stock import DeadStockAssessmentPageResponse, DeadStockAssessmentResponse, LatestDeadStockAssessmentResponse
from app.services.dead_stock_service import DeadStockService
from app.services.product_service import ProductService

router = APIRouter(tags=["dead-stock"])


@router.get("/dead-stock/assessments", response_model=DeadStockAssessmentPageResponse)
def list_dead_stock_assessments(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    classification: DeadStockClassification | None = Query(None),
    product_id: UUID | None = Query(None),
    category: str | None = Query(None),
    marketplace: str | None = Query(None),
    min_age_days: int | None = Query(None, ge=0),
    max_age_days: int | None = Query(None, ge=0),
    min_days_since_last_sale: int | None = Query(None, ge=0),
    max_days_since_last_sale: int | None = Query(None, ge=0),
    visibility_status: DeadStockVisibilityStatus | None = Query(None),
    data_status: DeadStockDataStatus | None = Query(None),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> DeadStockAssessmentPageResponse:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date range.")
    if min_age_days is not None and max_age_days is not None and min_age_days > max_age_days:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid age range.")
    if (
        min_days_since_last_sale is not None
        and max_days_since_last_sale is not None
        and min_days_since_last_sale > max_days_since_last_sale
    ):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid last-sale range.")
    if product_id and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    items, total = DeadStockService(db).list_assessments(
        seller_id=current_seller.id,
        classification=classification,
        product_id=product_id,
        category=category,
        marketplace=marketplace,
        min_age_days=min_age_days,
        max_age_days=max_age_days,
        min_days_since_last_sale=min_days_since_last_sale,
        max_days_since_last_sale=max_days_since_last_sale,
        visibility_status=visibility_status,
        data_status=data_status,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    return DeadStockAssessmentPageResponse(
        items=[DeadStockAssessmentResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/products/{product_id}/dead-stock/assessment", response_model=LatestDeadStockAssessmentResponse)
def get_latest_product_dead_stock_assessment(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    calculation_version: str | None = Query(None, max_length=20),
) -> LatestDeadStockAssessmentResponse:
    item = DeadStockService(db).latest_assessment(
        seller_id=current_seller.id,
        product_id=product_id,
        calculation_version=calculation_version,
    )
    if item is None and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return LatestDeadStockAssessmentResponse(
        item=DeadStockAssessmentResponse.model_validate(item) if item else None,
    )


@router.get("/products/{product_id}/dead-stock/history", response_model=DeadStockAssessmentPageResponse)
def get_product_dead_stock_history(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    calculation_version: str | None = Query(None, max_length=20),
) -> DeadStockAssessmentPageResponse:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date range.")
    items, total = DeadStockService(db).assessment_history(
        seller_id=current_seller.id,
        product_id=product_id,
        from_date=from_date,
        to_date=to_date,
        calculation_version=calculation_version,
        order=order,
        limit=limit,
        offset=offset,
    )
    if total == 0 and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return DeadStockAssessmentPageResponse(
        items=[DeadStockAssessmentResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
