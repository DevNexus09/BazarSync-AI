from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.sales_import import SalesImportRequest, SalesImportResponse
from app.services.sales_import_service import SalesImportService

router = APIRouter(prefix="/sales", tags=["sales-import"])


@router.post("/import", response_model=SalesImportResponse, status_code=status.HTTP_201_CREATED)
def import_sales_records(
    payload: SalesImportRequest,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> SalesImportResponse:
    try:
        return SalesImportService(db).import_records(seller_id=current_seller.id, payload=payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
