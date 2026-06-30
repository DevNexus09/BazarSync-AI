from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.repositories.phase5_dashboard_repository import Phase5DashboardRepository
from app.schemas.scrape import (
    CompetitorDashboardSummaryResponse,
    FeedPageResponse,
    MarketPositionCardResponse,
)
from app.services.competitor_ranking_service import CompetitorRankingService
from app.services.product_service import ProductService

router = APIRouter(prefix="/competitor-dashboard", tags=["competitor-dashboard"])


@router.get("/summary", response_model=CompetitorDashboardSummaryResponse)
def competitor_dashboard_summary(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    product_id: UUID | None = Query(None),
    window_hours: int = Query(settings.phase5_dashboard_summary_window_hours, ge=1, le=168),
) -> CompetitorDashboardSummaryResponse:
    _ensure_product(db, current_seller, product_id)
    return CompetitorDashboardSummaryResponse.model_validate(
        Phase5DashboardRepository(db).summary(
            seller_id=current_seller.id,
            product_id=product_id,
            window_hours=window_hours,
        )
    )


@router.get("/latest-price-changes", response_model=FeedPageResponse)
def latest_price_changes(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    product_id: UUID | None = Query(None),
    window_hours: int = Query(settings.phase5_dashboard_summary_window_hours, ge=1, le=168),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> FeedPageResponse:
    _ensure_product(db, current_seller, product_id)
    rows, total = Phase5DashboardRepository(db).price_changes(
        seller_id=current_seller.id,
        product_id=product_id,
        window_hours=window_hours,
        limit=limit,
        offset=offset,
    )
    return FeedPageResponse(
        items=[_price_change(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/activity-feed", response_model=FeedPageResponse)
def competitor_activity_feed(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    product_id: UUID | None = Query(None),
    window_hours: int = Query(settings.phase5_dashboard_summary_window_hours, ge=1, le=168),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> FeedPageResponse:
    _ensure_product(db, current_seller, product_id)
    rows, total = Phase5DashboardRepository(db).activity_feed(
        seller_id=current_seller.id,
        product_id=product_id,
        window_hours=window_hours,
        limit=limit,
        offset=offset,
    )
    return FeedPageResponse(
        items=[_activity(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/opportunity-feed", response_model=FeedPageResponse)
def opportunity_feed(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    product_id: UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> FeedPageResponse:
    _ensure_product(db, current_seller, product_id)
    rows, total = Phase5DashboardRepository(db).opportunity_feed(
        seller_id=current_seller.id,
        product_id=product_id,
        limit=limit,
        offset=offset,
    )
    return FeedPageResponse(
        items=[_opportunity(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/top-competitors", response_model=FeedPageResponse)
def top_competitors(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    product_id: UUID | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
) -> FeedPageResponse:
    _ensure_product(db, current_seller, product_id)
    rows, total = Phase5DashboardRepository(db).top_competitors(
        seller_id=current_seller.id,
        product_id=product_id,
        limit=limit,
    )
    return FeedPageResponse(
        items=[_top_competitor(row) for row in rows],
        total=total,
        limit=limit,
        offset=0,
    )


@router.get("/products/{product_id}/market-position-card", response_model=MarketPositionCardResponse)
def dashboard_market_position_card(
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


def _ensure_product(db: Session, current_seller: Seller, product_id: UUID | None) -> None:
    if product_id and not ProductService(db).get_product(current_seller.id, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")


def _price_change(row) -> dict:
    event, product_title, competitor_title = row
    event_type = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
    return {
        "event_type": event_type,
        "competitor_id": event.competitor_id,
        "competitor": competitor_title,
        "product_id": event.product_id,
        "product": product_title,
        "old_price": (event.old_value or {}).get("price"),
        "new_price": (event.new_value or {}).get("price"),
        "change_amount": event.price_change_amount,
        "change_percentage": event.price_change_percent,
        "event_time": event.detected_at,
        "severity": event.severity.value if hasattr(event.severity, "value") else event.severity,
    }


def _activity(row) -> dict:
    event, product_title, competitor_title = row
    event_type = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
    return {
        "event_type": event_type,
        "competitor_id": event.competitor_id,
        "competitor": competitor_title,
        "product_id": event.product_id,
        "product": product_title,
        "description": _event_description(event_type),
        "severity": event.severity.value if hasattr(event.severity, "value") else event.severity,
        "event_time": event.detected_at,
        "supporting_values": {"old": event.old_value, "new": event.new_value},
    }


def _opportunity(row) -> dict:
    opportunity, _product_title = row
    return {
        "id": opportunity.id,
        "opportunity_level": opportunity.opportunity_level.value if hasattr(opportunity.opportunity_level, "value") else opportunity.opportunity_level,
        "opportunity_score": opportunity.opportunity_score,
        "estimated_revenue": opportunity.estimated_revenue,
        "estimated_revenue_state": "estimated" if opportunity.estimated_revenue is not None else "insufficient_data",
        "recommended_action": opportunity.recommended_action.value if hasattr(opportunity.recommended_action, "value") else opportunity.recommended_action,
        "confidence_score": opportunity.confidence_score,
        "explanation": opportunity.explanation,
        "evidence": opportunity.evidence,
        "status": opportunity.status.value if hasattr(opportunity.status, "value") else opportunity.status,
        "detected_at": opportunity.detected_at,
    }


def _top_competitor(row) -> dict:
    ranking, product_title, competitor_title, competitor_store, price, rating, review_count, stock_status, source_url = row
    return {
        "id": ranking.id,
        "competitor_id": ranking.competitor_id,
        "competitor": competitor_title,
        "competitor_store": competitor_store,
        "product_id": ranking.product_id,
        "product": product_title,
        "scrape_run_id": ranking.scrape_run_id,
        "market_rank": ranking.market_rank,
        "total_score": ranking.total_score,
        "price_score": ranking.price_score,
        "rating_score": ranking.rating_score,
        "review_score": ranking.review_score,
        "availability_score": ranking.availability_score,
        "price": price,
        "rating": rating,
        "review_count": review_count,
        "stock_status": stock_status,
        "source_url": source_url,
        "calculated_at": ranking.calculated_at,
    }


def _event_description(event_type: str) -> str:
    return {
        "PRICE_DROP": "Competitor price dropped.",
        "PRICE_RISE": "Competitor price rose.",
        "OUT_OF_STOCK": "Competitor went out of stock.",
        "BACK_IN_STOCK": "Competitor returned to stock.",
        "NEW_COMPETITOR": "New competitor appeared.",
        "COMPETITOR_REMOVED": "Competitor appears removed after completed scrapes.",
    }.get(event_type, "Competitor activity detected.")
