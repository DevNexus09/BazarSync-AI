from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.dead_stock_assessment import DeadStockClassification, DeadStockDataStatus, DeadStockRiskLevel
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.models.seller import Seller
from app.schemas.dead_stock_dashboard import (
    DeadStockProductIntelligenceResponse,
    DeadStockProductPageResponse,
    DeadStockSummaryResponse,
)
from app.schemas.dead_stock_readiness import DeadStockReadinessResponse, DeadStockRecalculationResponse
from app.services.dead_stock_dashboard_service import DeadStockDashboardService
from app.services.dead_stock_readiness_service import DeadStockReadinessService
from app.services.product_service import ProductService

router = APIRouter(tags=["dead-stock-dashboard"])


@router.get("/dead-stock/summary", response_model=DeadStockSummaryResponse)
def get_dead_stock_summary(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> DeadStockSummaryResponse:
    return DeadStockDashboardService(db).summary(seller_id=current_seller.id)


@router.get("/dead-stock/products", response_model=DeadStockProductPageResponse)
def get_dead_stock_products(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    classification: DeadStockClassification | None = Query(None),
    risk_level: DeadStockRiskLevel | None = Query(None),
    category: str | None = Query(None),
    marketplace: str | None = Query(None),
    min_age_days: int | None = Query(None, ge=0),
    min_locked_capital: Decimal | None = Query(None, ge=0),
    recommendation_action: DeadStockRecoveryAction | None = Query(None),
    data_status: DeadStockDataStatus | None = Query(None),
    sort: str = Query("risk", pattern="^(risk|age|locked_capital|potential_recovery)$"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> DeadStockProductPageResponse:
    return DeadStockDashboardService(db).products(
        seller_id=current_seller.id,
        classification=classification,
        risk_level=risk_level,
        category=category,
        marketplace=marketplace,
        min_age_days=min_age_days,
        min_locked_capital=min_locked_capital,
        recommendation_action=recommendation_action,
        data_status=data_status,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/products/{product_id}/dead-stock/intelligence", response_model=DeadStockProductIntelligenceResponse)
def get_product_dead_stock_intelligence(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> DeadStockProductIntelligenceResponse:
    item = DeadStockDashboardService(db).product_intelligence(
        seller_id=current_seller.id,
        product_id=product_id,
    )
    if item is None and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dead-stock intelligence not found.")
    return item


@router.get("/products/{product_id}/dead-stock/readiness", response_model=DeadStockReadinessResponse)
def get_product_dead_stock_readiness(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> DeadStockReadinessResponse:
    readiness = DeadStockReadinessService(db).evaluate(
        seller_id=current_seller.id,
        product_id=product_id,
    )
    if readiness is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return readiness


@router.post("/products/{product_id}/dead-stock/recalculate", response_model=DeadStockRecalculationResponse, status_code=status.HTTP_202_ACCEPTED)
def recalculate_product_dead_stock(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> DeadStockRecalculationResponse:
    service = DeadStockReadinessService(db)
    readiness = service.evaluate(seller_id=current_seller.id, product_id=product_id)
    if readiness is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    from app.tasks.dead_stock_workflow_tasks import enqueue_dead_stock_recalculation

    enqueued = enqueue_dead_stock_recalculation(
        seller_id=current_seller.id,
        product_id=product_id,
        reason="inventory_adjustment",
    )
    return DeadStockRecalculationResponse(
        product_id=product_id,
        enqueued=enqueued,
        message=(
            "Dead stock recalculation has been queued."
            if enqueued
            else "Dead stock recalculation was not queued because a duplicate request is already pending or the worker is unavailable."
        ),
        readiness=readiness,
    )
