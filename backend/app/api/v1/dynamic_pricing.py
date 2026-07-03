from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.dynamic_pricing_recommendation import DynamicPricingRecommendationStatus
from app.models.seller import Seller
from app.schemas.dynamic_pricing import DynamicPricingLatestResponse, DynamicPricingRecommendationPageResponse, DynamicPricingRecommendationResponse
from app.services.dynamic_pricing_service import DynamicPricingService

router = APIRouter(tags=["dynamic-pricing"])


@router.post("/products/{product_id}/pricing/recommendations", response_model=DynamicPricingRecommendationResponse)
def generate_dynamic_pricing_recommendation(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> DynamicPricingRecommendationResponse:
    try:
        return DynamicPricingService(db).generate_for_product(seller_id=current_seller.id, product_id=product_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/products/{product_id}/pricing/recommendations/latest", response_model=DynamicPricingLatestResponse)
def get_latest_dynamic_pricing_recommendation(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> DynamicPricingLatestResponse:
    try:
        return DynamicPricingLatestResponse(item=DynamicPricingService(db).latest(seller_id=current_seller.id, product_id=product_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/products/{product_id}/pricing/recommendations", response_model=DynamicPricingRecommendationPageResponse)
def list_dynamic_pricing_recommendations(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> DynamicPricingRecommendationPageResponse:
    try:
        items, total = DynamicPricingService(db).list_product(seller_id=current_seller.id, product_id=product_id, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DynamicPricingRecommendationPageResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/pricing/recommendations/{recommendation_id}", response_model=DynamicPricingRecommendationResponse)
def get_dynamic_pricing_recommendation(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> DynamicPricingRecommendationResponse:
    item = DynamicPricingService(db).get(seller_id=current_seller.id, recommendation_id=recommendation_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found.")
    return item


@router.post("/pricing/recommendations/{recommendation_id}/acknowledge", response_model=DynamicPricingRecommendationResponse)
def acknowledge_dynamic_pricing_recommendation(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> DynamicPricingRecommendationResponse:
    try:
        return DynamicPricingService(db).update_status(
            seller_id=current_seller.id,
            recommendation_id=recommendation_id,
            status=DynamicPricingRecommendationStatus.ACKNOWLEDGED,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/pricing/recommendations/{recommendation_id}/dismiss", response_model=DynamicPricingRecommendationResponse)
def dismiss_dynamic_pricing_recommendation(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> DynamicPricingRecommendationResponse:
    try:
        return DynamicPricingService(db).update_status(
            seller_id=current_seller.id,
            recommendation_id=recommendation_id,
            status=DynamicPricingRecommendationStatus.DISMISSED,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
