from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.dead_stock_recovery import (
    DeadStockRecoveryRecommendationPageResponse,
    DeadStockRecoveryRecommendationResponse,
    LatestDeadStockRecoveryRecommendationResponse,
)
from app.services.dead_stock_recovery_service import DeadStockRecoveryService
from app.services.product_service import ProductService

router = APIRouter(tags=["dead-stock-recovery"])


@router.get("/products/{product_id}/dead-stock/recommendation", response_model=LatestDeadStockRecoveryRecommendationResponse)
def get_latest_dead_stock_recovery_recommendation(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> LatestDeadStockRecoveryRecommendationResponse:
    item = DeadStockRecoveryService(db).latest_recommendation(
        seller_id=current_seller.id,
        product_id=product_id,
    )
    if item is None and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return LatestDeadStockRecoveryRecommendationResponse(
        item=DeadStockRecoveryRecommendationResponse.model_validate(item) if item else None,
    )


@router.get("/products/{product_id}/dead-stock/recommendations", response_model=DeadStockRecoveryRecommendationPageResponse)
def get_dead_stock_recovery_recommendations(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> DeadStockRecoveryRecommendationPageResponse:
    if not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    items, total = DeadStockRecoveryService(db).recommendation_history(
        seller_id=current_seller.id,
        product_id=product_id,
        limit=limit,
        offset=offset,
    )
    return DeadStockRecoveryRecommendationPageResponse(
        items=[DeadStockRecoveryRecommendationResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/dead-stock/recommendations/{recommendation_id}/acknowledge", response_model=DeadStockRecoveryRecommendationResponse)
def acknowledge_dead_stock_recovery_recommendation(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> DeadStockRecoveryRecommendationResponse:
    item = DeadStockRecoveryService(db).acknowledge(
        seller_id=current_seller.id,
        recommendation_id=recommendation_id,
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found.")
    return DeadStockRecoveryRecommendationResponse.model_validate(item)


@router.post("/dead-stock/recommendations/{recommendation_id}/dismiss", response_model=DeadStockRecoveryRecommendationResponse)
def dismiss_dead_stock_recovery_recommendation(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> DeadStockRecoveryRecommendationResponse:
    item = DeadStockRecoveryService(db).dismiss(
        seller_id=current_seller.id,
        recommendation_id=recommendation_id,
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found.")
    return DeadStockRecoveryRecommendationResponse.model_validate(item)
