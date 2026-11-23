from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.recommendation_outcome import RecommendationOutcomeType
from app.models.seller import Seller
from app.services.recommendation_outcome_service import RecommendationOutcomeService

router = APIRouter(prefix="/recommendation-outcomes", tags=["recommendation-outcomes"])


@router.get("/track-record")
def get_track_record(
    recommendation_type: RecommendationOutcomeType = Query(...),
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> dict[str, object]:
    if not settings.recommendation_outcomes_enabled:
        return {"enabled": False, "recommendation_type": recommendation_type.value}
    record = RecommendationOutcomeService(db).track_record(seller_id=current_seller.id, recommendation_type=recommendation_type)
    return {"enabled": True, **record}
