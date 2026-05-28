"""Dashboard API routes."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.async_db import get_async_db
from app.models.alert import (
    Alert,
    AlertActionType,
    AlertDeliveryStatus,
    AlertUrgencyLevel,
)
from app.models.recommendation import RecommendationAction, RecommendationConfidence
from app.repositories.alert_repository import AlertRepository
from app.repositories.competitor_repository import CompetitorRepository
from app.repositories.query_utils import PaginationParams, SortDirection
from app.repositories.recommendation_repository import RecommendationRepository
from app.schemas.dashboard.alert_schema import AlertListResponse, AlertSortField
from app.schemas.dashboard.competitor_schema import CompetitorListResponse, CompetitorSortField
from app.schemas.dashboard.opportunity_schema import OpportunityListResponse, OpportunitySortField
from app.schemas.dashboard.recommendation_schema import (
    RecommendationListResponse,
    RecommendationSortField,
)
from app.schemas.dashboard.summary_schema import DashboardSummaryResponse
from app.services.dashboard.alert_service import AlertDashboardService
from app.services.dashboard.competitor_service import CompetitorDashboardService
from app.services.dashboard.dashboard_service import DashboardService
from app.services.dashboard.opportunity_service import OpportunityDashboardService
from app.services.dashboard.recommendation_service import RecommendationDashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)


class AlertResolveResponse(BaseModel):
    id: str
    status: str


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    seller_id: UUID | None = Query(None, description="Filter by seller"),
    db: AsyncSession = Depends(get_async_db),
) -> DashboardSummaryResponse:
    start = time.monotonic()
    service = DashboardService(db, logger=logger)
    response = await service.get_summary(seller_id=str(seller_id) if seller_id else None)
    _log_endpoint("dashboard_summary", start, seller_id=seller_id)
    return response


@router.get("/competitors", response_model=CompetitorListResponse)
async def list_competitors(
    seller_id: UUID | None = Query(None, description="Filter by seller"),
    product_id: UUID | None = Query(None, description="Filter by product"),
    stock_status: str | None = Query(None, description="Filter by stock status"),
    search: str | None = Query(None, min_length=2, description="Search competitor or product"),
    sort_by: CompetitorSortField = Query(
        CompetitorSortField.created_at, description="Sort field"
    ),
    sort_direction: SortDirection = Query(
        SortDirection.desc, description="Sort direction"
    ),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
) -> CompetitorListResponse:
    start = time.monotonic()
    pagination = PaginationParams.from_request(
        limit=limit, offset=offset, page=page, page_size=page_size, max_page_size=200
    )
    service = CompetitorDashboardService(CompetitorRepository(db), logger=logger)
    response = await service.list_competitors(
        seller_id=str(seller_id) if seller_id else None,
        product_id=str(product_id) if product_id else None,
        stock_status=stock_status,
        search=search,
        sort_by=sort_by.value,
        sort_direction=sort_direction,
        pagination=pagination,
    )
    _log_endpoint("dashboard_competitors", start, seller_id=seller_id)
    return response


@router.get("/recommendations", response_model=RecommendationListResponse)
async def list_recommendations(
    seller_id: UUID | None = Query(None, description="Filter by seller"),
    product_id: UUID | None = Query(None, description="Filter by product"),
    action_type: RecommendationAction | None = Query(None, description="Filter by action"),
    confidence: RecommendationConfidence | None = Query(
        None, description="Filter by confidence"
    ),
    search: str | None = Query(None, min_length=2, description="Search by product or reasoning"),
    date_from: datetime | None = Query(None, description="Start date"),
    date_to: datetime | None = Query(None, description="End date"),
    sort_by: RecommendationSortField = Query(
        RecommendationSortField.created_at, description="Sort field"
    ),
    sort_direction: SortDirection = Query(SortDirection.desc, description="Sort direction"),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
) -> RecommendationListResponse:
    start = time.monotonic()
    pagination = PaginationParams.from_request(
        limit=limit, offset=offset, page=page, page_size=page_size, max_page_size=200
    )
    service = RecommendationDashboardService(RecommendationRepository(db), logger=logger)
    response = await service.list_recommendations(
        seller_id=str(seller_id) if seller_id else None,
        product_id=str(product_id) if product_id else None,
        action_type=action_type.value if action_type else None,
        confidence=confidence.value if confidence else None,
        search=search,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by.value,
        sort_direction=sort_direction,
        pagination=pagination,
    )
    _log_endpoint("dashboard_recommendations", start, seller_id=seller_id)
    return response


@router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    seller_id: UUID | None = Query(None, description="Filter by seller"),
    product_id: UUID | None = Query(None, description="Filter by product"),
    urgency_level: AlertUrgencyLevel | None = Query(
        None, description="Filter by urgency level"
    ),
    action_type: AlertActionType | None = Query(
        None, description="Filter by action type"
    ),
    delivery_status: AlertDeliveryStatus | None = Query(
        None, description="Filter by delivery status"
    ),
    is_read: bool | None = Query(None, description="Filter by read status"),
    date_from: datetime | None = Query(None, description="Start date"),
    date_to: datetime | None = Query(None, description="End date"),
    sort_by: AlertSortField = Query(AlertSortField.created_at, description="Sort field"),
    sort_direction: SortDirection = Query(SortDirection.desc, description="Sort direction"),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
) -> AlertListResponse:
    start = time.monotonic()
    pagination = PaginationParams.from_request(
        limit=limit, offset=offset, page=page, page_size=page_size, max_page_size=200
    )
    service = AlertDashboardService(AlertRepository(db), logger=logger)
    response = await service.list_alerts(
        seller_id=str(seller_id) if seller_id else None,
        product_id=str(product_id) if product_id else None,
        urgency_level=urgency_level.value if urgency_level else None,
        action_type=action_type.value if action_type else None,
        delivery_status=delivery_status.value if delivery_status else None,
        is_read=is_read,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by.value,
        sort_direction=sort_direction,
        pagination=pagination,
    )
    _log_endpoint("dashboard_alerts", start, seller_id=seller_id)
    return response


@router.get("/market-opportunities", response_model=OpportunityListResponse)
async def list_market_opportunities(
    seller_id: UUID | None = Query(None, description="Filter by seller"),
    min_revenue: float | None = Query(None, ge=0, description="Minimum revenue opportunity"),
    date_from: datetime | None = Query(None, description="Start date"),
    date_to: datetime | None = Query(None, description="End date"),
    sort_by: OpportunitySortField = Query(
        OpportunitySortField.revenue_opportunity, description="Sort field"
    ),
    sort_direction: SortDirection = Query(SortDirection.desc, description="Sort direction"),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
) -> OpportunityListResponse:
    start = time.monotonic()
    pagination = PaginationParams.from_request(
        limit=limit, offset=offset, page=page, page_size=page_size, max_page_size=200
    )
    service = OpportunityDashboardService(RecommendationRepository(db), logger=logger)
    response = await service.list_opportunities(
        seller_id=str(seller_id) if seller_id else None,
        min_revenue=min_revenue,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by.value,
        sort_direction=sort_direction,
        pagination=pagination,
    )
    _log_endpoint("dashboard_opportunities", start, seller_id=seller_id)
    return response


@router.patch("/alerts/{alert_id}/resolve", response_model=AlertResolveResponse)
async def resolve_alert(
    alert_id: UUID,
    db: AsyncSession = Depends(get_async_db),
) -> AlertResolveResponse:
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")
    if alert.read_at is None:
        alert.read_at = datetime.now(timezone.utc)
        await db.commit()
    return AlertResolveResponse(id=str(alert.id), status="resolved")


def _log_endpoint(name: str, start: float, **fields: Any) -> None:
    duration_ms = int((time.monotonic() - start) * 1000)
    payload = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    logger.info("%s duration_ms=%s %s", name, duration_ms, payload)
