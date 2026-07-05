from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.product_visibility_metric import (
    ProductVisibilityMetricCreate,
    ProductVisibilityMetricHistoryResponse,
    ProductVisibilityMetricResponse,
)
from app.services.product_visibility_service import ProductVisibilityService

router = APIRouter(prefix="/products", tags=["visibility-metrics"])


@router.post("/{product_id}/visibility-metrics", response_model=ProductVisibilityMetricResponse, status_code=status.HTTP_201_CREATED)
def create_product_visibility_metric(
    product_id: UUID,
    payload: ProductVisibilityMetricCreate,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ProductVisibilityMetricResponse:
    try:
        return ProductVisibilityService(db).create(seller_id=current_seller.id, product_id=product_id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Visibility metrics already exist for this product, marketplace, date, and source.") from exc


@router.get("/{product_id}/visibility-metrics/latest", response_model=ProductVisibilityMetricResponse)
def get_latest_product_visibility_metric(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ProductVisibilityMetricResponse:
    try:
        item = ProductVisibilityService(db).latest(seller_id=current_seller.id, product_id=product_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visibility metrics not found.")
    return item


@router.get("/{product_id}/visibility-metrics/history", response_model=ProductVisibilityMetricHistoryResponse)
def get_product_visibility_metric_history(
    product_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ProductVisibilityMetricHistoryResponse:
    try:
        items, total = ProductVisibilityService(db).history(
            seller_id=current_seller.id,
            product_id=product_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ProductVisibilityMetricHistoryResponse(items=items, total=total, limit=limit, offset=offset)
