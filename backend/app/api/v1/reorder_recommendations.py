from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.reorder_recommendation import ReorderRecommendationStatus
from app.models.seller import Seller
from app.schemas.reorder_recommendation import ReorderRecommendationResponse
from app.services.reorder_recommendation_service import (
    ReorderRecommendationNotFoundError,
    ReorderRecommendationService,
)

router = APIRouter(prefix="/reorder-recommendations", tags=["reorder-recommendations"])


@router.post("/{recommendation_id}/acknowledge", response_model=ReorderRecommendationResponse)
def acknowledge_reorder_recommendation(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ReorderRecommendationResponse:
    return _transition(db, current_seller, recommendation_id, ReorderRecommendationStatus.ACKNOWLEDGED)


@router.post("/{recommendation_id}/mark-ordered", response_model=ReorderRecommendationResponse)
def mark_reorder_recommendation_ordered(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ReorderRecommendationResponse:
    return _transition(db, current_seller, recommendation_id, ReorderRecommendationStatus.ORDERED)


@router.post("/{recommendation_id}/dismiss", response_model=ReorderRecommendationResponse)
def dismiss_reorder_recommendation(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ReorderRecommendationResponse:
    return _transition(db, current_seller, recommendation_id, ReorderRecommendationStatus.DISMISSED)


def _transition(
    db: Session,
    current_seller: Seller,
    recommendation_id: UUID,
    target_status: ReorderRecommendationStatus,
) -> ReorderRecommendationResponse:
    try:
        recommendation = ReorderRecommendationService(db).transition_status(
            seller_id=current_seller.id,
            recommendation_id=recommendation_id,
            status=target_status,
        )
    except ReorderRecommendationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found.") from exc
    return ReorderRecommendationResponse.model_validate(recommendation)
