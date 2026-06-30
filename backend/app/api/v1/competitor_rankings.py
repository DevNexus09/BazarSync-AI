from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.scrape import (
    CompetitorRankingExcludedResponse,
    CompetitorRankingMetadataResponse,
    CompetitorRankingPageResponse,
    CompetitorRankingResponse,
    MarketPositionCardResponse,
)
from app.services.competitor_ranking_service import CompetitorRankingService
from app.services.product_service import ProductService

router = APIRouter(prefix="/competitor-rankings", tags=["competitor-rankings"])


@router.get("/products/{product_id}/latest", response_model=CompetitorRankingPageResponse)
def latest_product_rankings(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> CompetitorRankingPageResponse:
    _ensure_product(db, current_seller, product_id)
    items, total = CompetitorRankingService(db).latest_for_product(
        seller_id=current_seller.id,
        product_id=product_id,
        limit=limit,
        offset=offset,
    )
    return _page(items, total, limit, offset)


@router.get("/products/{product_id}/top", response_model=CompetitorRankingPageResponse)
def current_top_competitors(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    limit: int = Query(5, ge=1, le=50),
) -> CompetitorRankingPageResponse:
    _ensure_product(db, current_seller, product_id)
    items, total = CompetitorRankingService(db).latest_for_product(
        seller_id=current_seller.id,
        product_id=product_id,
        limit=limit,
        offset=0,
    )
    return _page(items, total, limit, 0)


@router.get("/products/{product_id}/history", response_model=CompetitorRankingPageResponse)
def product_ranking_history(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    formula_version: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> CompetitorRankingPageResponse:
    _ensure_product(db, current_seller, product_id)
    items, total = CompetitorRankingService(db).history_for_product(
        seller_id=current_seller.id,
        product_id=product_id,
        formula_version=formula_version,
        limit=limit,
        offset=offset,
    )
    return _page(items, total, limit, offset)


@router.get("/products/{product_id}/competitors/{competitor_id}/history", response_model=CompetitorRankingPageResponse)
def competitor_score_history(
    product_id: UUID,
    competitor_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    formula_version: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> CompetitorRankingPageResponse:
    _ensure_product(db, current_seller, product_id)
    items, total = CompetitorRankingService(db).history_for_competitor(
        seller_id=current_seller.id,
        product_id=product_id,
        competitor_id=competitor_id,
        formula_version=formula_version,
        limit=limit,
        offset=offset,
    )
    return _page(items, total, limit, offset)


@router.get("/products/{product_id}/metadata", response_model=CompetitorRankingMetadataResponse)
def ranking_metadata(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> CompetitorRankingMetadataResponse:
    _ensure_product(db, current_seller, product_id)
    return CompetitorRankingMetadataResponse.model_validate(
        CompetitorRankingService(db).metadata_for_product(
            seller_id=current_seller.id,
            product_id=product_id,
        )
    )


@router.get("/products/{product_id}/excluded", response_model=CompetitorRankingExcludedResponse)
def excluded_ranking_records(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> CompetitorRankingExcludedResponse:
    _ensure_product(db, current_seller, product_id)
    items = CompetitorRankingService(db).excluded_for_latest_product(
        seller_id=current_seller.id,
        product_id=product_id,
    )
    return CompetitorRankingExcludedResponse(items=items, total=len(items))


@router.get("/products/{product_id}/market-position-card", response_model=MarketPositionCardResponse)
def market_position_card(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> MarketPositionCardResponse:
    _ensure_product(db, current_seller, product_id)
    return MarketPositionCardResponse.model_validate(
        CompetitorRankingService(db).market_position_card(
            seller_id=current_seller.id,
            product_id=product_id,
        )
    )


def _ensure_product(db: Session, current_seller: Seller, product_id: UUID) -> None:
    if not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")


def _page(items, total: int, limit: int, offset: int) -> CompetitorRankingPageResponse:
    return CompetitorRankingPageResponse(
        items=[CompetitorRankingResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
