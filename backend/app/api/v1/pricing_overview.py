from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.pricing_overview import PricingOverviewResponse
from app.services.pricing_overview_service import PricingOverviewService

router = APIRouter(tags=["pricing-analytics"])


@router.get("/pricing/overview", response_model=PricingOverviewResponse)
def get_pricing_overview(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> PricingOverviewResponse:
    return PricingOverviewService(db).overview(seller_id=current_seller.id, limit=limit, offset=offset)
