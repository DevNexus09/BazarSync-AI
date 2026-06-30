from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.scrape import MarketOpportunityPageResponse, MarketOpportunityResponse
from app.services.market_opportunity_service import MarketOpportunityService
from app.services.product_service import ProductService

router = APIRouter(prefix="/market-opportunities", tags=["market-opportunities"])


@router.get("", response_model=MarketOpportunityPageResponse)
def list_market_opportunities(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    product_id: UUID | None = Query(None),
    level: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    recent_closed: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> MarketOpportunityPageResponse:
    if product_id and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    items, total = MarketOpportunityService(db).list_opportunities(
        seller_id=current_seller.id,
        product_id=product_id,
        level=level.upper() if level else None,
        status=status_filter.upper() if status_filter else None,
        recent_closed=recent_closed,
        limit=limit,
        offset=offset,
    )
    return _page(items, total, limit, offset)


@router.get("/{opportunity_id}", response_model=MarketOpportunityResponse)
def get_market_opportunity(
    opportunity_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> MarketOpportunityResponse:
    opportunity = MarketOpportunityService(db).get_detail(
        seller_id=current_seller.id,
        opportunity_id=opportunity_id,
    )
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found.")
    return MarketOpportunityResponse.model_validate(opportunity)


@router.post("/{opportunity_id}/acknowledge", response_model=MarketOpportunityResponse)
def acknowledge_market_opportunity(
    opportunity_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> MarketOpportunityResponse:
    opportunity = MarketOpportunityService(db).acknowledge(
        seller_id=current_seller.id,
        opportunity_id=opportunity_id,
    )
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found.")
    return MarketOpportunityResponse.model_validate(opportunity)


@router.post("/{opportunity_id}/dismiss", response_model=MarketOpportunityResponse)
def dismiss_market_opportunity(
    opportunity_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> MarketOpportunityResponse:
    opportunity = MarketOpportunityService(db).dismiss(
        seller_id=current_seller.id,
        opportunity_id=opportunity_id,
    )
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found.")
    return MarketOpportunityResponse.model_validate(opportunity)


def _page(items, total: int, limit: int, offset: int) -> MarketOpportunityPageResponse:
    return MarketOpportunityPageResponse(
        items=[MarketOpportunityResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
