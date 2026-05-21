from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.competitor import CompetitorListResponse, CompetitorResponse
from app.services.competitor_service import CompetitorService, ProductNotFoundError

router = APIRouter(prefix="/competitors", tags=["competitors"])


@router.get("/{product_id}", response_model=CompetitorListResponse)
def list_competitors(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> CompetitorListResponse:
    service = CompetitorService(db)
    try:
        competitors, total, _ = service.list_latest_competitors(
            current_seller.id,
            product_id,
            limit=limit,
            offset=offset,
        )
    except ProductNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        ) from exc

    items = [
        CompetitorResponse(
            id=competitor.id,
            product_id=competitor.product_id,
            scrape_run_id=competitor.scrape_run_id,
            competitor_title=competitor.competitor_title,
            competitor_description=competitor.competitor_description,
            competitor_category=competitor.competitor_category,
            competitor_brand=competitor.competitor_brand,
            competitor_attributes=competitor.competitor_attributes,
            competitor_price=competitor.competitor_price,
            competitor_rating=competitor.competitor_rating,
            competitor_sold=competitor.competitor_sold,
            stock_status=competitor.stock_status,
            similarity_score=competitor.similarity_score,
            title_similarity=competitor.title_similarity,
            description_similarity=competitor.description_similarity,
            attribute_similarity=competitor.attribute_similarity,
            keyword_score=competitor.keyword_score,
            ranking_score=competitor.ranking_score,
            match_confidence=competitor.match_confidence,
            category_match=competitor.category_match,
            matched_attributes=competitor.matched_attributes,
            competitor_store=competitor.competitor_store,
            product_url=competitor.product_url,
            marketplace=competitor.marketplace,
            marketplace_position=competitor.search_position,
            created_at=competitor.created_at,
        )
        for competitor in competitors
    ]

    return CompetitorListResponse(items=items, total=total, limit=limit, offset=offset)
