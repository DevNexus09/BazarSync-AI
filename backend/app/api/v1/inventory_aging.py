from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.inventory_aging import (
    InventoryAgingBucketDistributionResponse,
    InventoryAgingHistoryResponse,
    InventoryAgingResponse,
    LatestInventoryAgingResponse,
)
from app.services.inventory_aging_service import InventoryAgingService
from app.services.product_service import ProductService

router = APIRouter(prefix="/products", tags=["inventory-aging"])


@router.get("/{product_id}/inventory-aging", response_model=LatestInventoryAgingResponse)
def get_latest_product_inventory_aging(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    calculation_version: str | None = Query(None, max_length=20),
) -> LatestInventoryAgingResponse:
    service = InventoryAgingService(db)
    item = service.latest_aging(
        seller_id=current_seller.id,
        product_id=product_id,
        calculation_version=calculation_version,
    )
    if item is None and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return LatestInventoryAgingResponse(
        item=InventoryAgingResponse.model_validate(item) if item else None,
        explanation=service.explain_age_source(item) if item else None,
    )


@router.get("/{product_id}/inventory-aging/history", response_model=InventoryAgingHistoryResponse)
def get_product_inventory_aging_history(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    calculation_version: str | None = Query(None, max_length=20),
) -> InventoryAgingHistoryResponse:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date range.")
    items, total = InventoryAgingService(db).aging_history(
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
    return InventoryAgingHistoryResponse(
        items=[InventoryAgingResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{product_id}/inventory-aging/buckets", response_model=InventoryAgingBucketDistributionResponse)
def get_product_inventory_aging_buckets(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    calculation_version: str | None = Query(None, max_length=20),
) -> InventoryAgingBucketDistributionResponse:
    if not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return InventoryAgingBucketDistributionResponse(
        product_id=product_id,
        age_buckets=InventoryAgingService(db).age_bucket_distribution(
            seller_id=current_seller.id,
            product_id=product_id,
            calculation_version=calculation_version,
        ),
    )
