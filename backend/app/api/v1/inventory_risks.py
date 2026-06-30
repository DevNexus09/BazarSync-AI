from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.inventory_risk import InventoryRiskLevel
from app.models.seller import Seller
from app.schemas.inventory_risk import InventoryRiskPageResponse, InventoryRiskResponse
from app.services.inventory_risk_service import InventoryRiskService
from app.services.product_service import ProductService

router = APIRouter(prefix="/inventory-risks", tags=["inventory-risks"])


@router.get("", response_model=InventoryRiskPageResponse)
def list_inventory_risks(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    risk_level: InventoryRiskLevel | None = Query(None),
    product_id: UUID | None = Query(None),
    category: str | None = Query(None),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    open_reorder_required: bool | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> InventoryRiskPageResponse:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date range.")
    if product_id and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    items, total = InventoryRiskService(db).list_risks(
        seller_id=current_seller.id,
        risk_level=risk_level,
        product_id=product_id,
        category=category,
        from_date=from_date,
        to_date=to_date,
        open_reorder_required=open_reorder_required,
        limit=limit,
        offset=offset,
    )
    return InventoryRiskPageResponse(
        items=[InventoryRiskResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
