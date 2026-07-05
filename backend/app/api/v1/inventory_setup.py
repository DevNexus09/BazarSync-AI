from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.inventory_stock_in import InventoryStockInCreate, InventoryStockInResponse
from app.services.inventory_stock_in_service import InventoryStockInService

router = APIRouter(prefix="/inventory", tags=["inventory-setup"])


@router.post("/stock-in", response_model=InventoryStockInResponse, status_code=status.HTTP_201_CREATED)
def create_inventory_stock_in(
    payload: InventoryStockInCreate,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> InventoryStockInResponse:
    try:
        record = InventoryStockInService(db).create(seller_id=current_seller.id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate stock-in source reference.") from exc
    return InventoryStockInResponse.model_validate(record)
