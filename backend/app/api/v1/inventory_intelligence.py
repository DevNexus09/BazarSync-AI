from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.inventory_risk import InventoryRiskLevel
from app.models.seller import Seller
from app.schemas.inventory_intelligence import (
    InventoryIntelligencePageResponse,
    InventoryIntelligenceSummaryResponse,
    InventoryWorkflowEnqueueResponse,
    ProductInventoryIntelligenceResponse,
)
from app.services.inventory_intelligence_service import InventoryIntelligenceService
from app.services.product_service import ProductService
from app.tasks.inventory_intelligence_workflow_tasks import (
    recalculate_product_inventory_intelligence_task,
    run_daily_inventory_intelligence_workflow,
)

router = APIRouter(prefix="/inventory-intelligence", tags=["inventory-intelligence"])


@router.get("/summary", response_model=InventoryIntelligenceSummaryResponse)
def get_inventory_intelligence_summary(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> InventoryIntelligenceSummaryResponse:
    return InventoryIntelligenceService(db).summary(seller_id=current_seller.id)


@router.get("/reorder-list", response_model=InventoryIntelligencePageResponse)
def get_reorder_list(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    risk_level: InventoryRiskLevel | None = Query(None),
    deadline_from: date | None = Query(None),
    deadline_to: date | None = Query(None),
    product_id: UUID | None = Query(None),
    category: str | None = Query(None),
    sort: str = Query("deadline", pattern="^(deadline|risk|recommended_quantity)$"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> InventoryIntelligencePageResponse:
    if deadline_from and deadline_to and deadline_from > deadline_to:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid deadline range.")
    if product_id and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    items, total = InventoryIntelligenceService(db).reorder_list(
        seller_id=current_seller.id,
        risk_level=risk_level,
        deadline_from=deadline_from,
        deadline_to=deadline_to,
        product_id=product_id,
        category=category,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return InventoryIntelligencePageResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/risks", response_model=InventoryIntelligencePageResponse)
def get_inventory_intelligence_risks(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    risk_level: InventoryRiskLevel | None = Query(None),
    insufficient_data: bool | None = Query(None),
    product_id: UUID | None = Query(None),
    category: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> InventoryIntelligencePageResponse:
    if product_id and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    items, total = InventoryIntelligenceService(db).risks(
        seller_id=current_seller.id,
        risk_level=risk_level,
        insufficient_data=insufficient_data,
        product_id=product_id,
        category=category,
        limit=limit,
        offset=offset,
    )
    return InventoryIntelligencePageResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/workflow/daily", response_model=InventoryWorkflowEnqueueResponse)
def enqueue_daily_inventory_intelligence_workflow(
    current_seller: Seller = Depends(get_current_seller),
    as_of_date: date | None = Query(None),
) -> InventoryWorkflowEnqueueResponse:
    result = run_daily_inventory_intelligence_workflow.delay(
        seller_id=str(current_seller.id),
        as_of_date=as_of_date.isoformat() if as_of_date else None,
    )
    return InventoryWorkflowEnqueueResponse(
        workflow_id=result.id,
        scope="seller",
        seller_id=current_seller.id,
        as_of_date=as_of_date,
    )


@router.post("/products/{product_id}/workflow", response_model=InventoryWorkflowEnqueueResponse)
def enqueue_product_inventory_intelligence_workflow(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    as_of_date: date | None = Query(None),
) -> InventoryWorkflowEnqueueResponse:
    if not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    result = recalculate_product_inventory_intelligence_task.delay(
        seller_id=str(current_seller.id),
        product_id=str(product_id),
        as_of_date=as_of_date.isoformat() if as_of_date else None,
        reason="manual_product_recalculation",
    )
    return InventoryWorkflowEnqueueResponse(
        workflow_id=result.id,
        scope="product",
        seller_id=current_seller.id,
        product_id=product_id,
        as_of_date=as_of_date,
    )


@router.get("/products/{product_id}", response_model=ProductInventoryIntelligenceResponse)
def get_product_inventory_intelligence_nested(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ProductInventoryIntelligenceResponse:
    return _get_product_intelligence(db, current_seller, product_id)


def _get_product_intelligence(
    db: Session,
    current_seller: Seller,
    product_id: UUID,
) -> ProductInventoryIntelligenceResponse:
    item = InventoryIntelligenceService(db).product_intelligence(
        seller_id=current_seller.id,
        product_id=product_id,
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return item
