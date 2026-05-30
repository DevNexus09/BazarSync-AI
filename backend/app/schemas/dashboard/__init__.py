from __future__ import annotations

from app.schemas.dashboard.alert_schema import AlertListResponse, AlertRecord
from app.schemas.dashboard.activity_schema import ActivityItem
from app.schemas.dashboard.competitor_schema import CompetitorListResponse, CompetitorRecord
from app.schemas.dashboard.error_schema import DashboardErrorResponse, ErrorDetail
from app.schemas.dashboard.market_trend_schema import MarketTrendPoint
from app.schemas.dashboard.opportunity_schema import OpportunityListResponse, OpportunityRecord
from app.schemas.dashboard.opportunity_metrics_schema import OpportunityMetricRecord
from app.schemas.dashboard.pagination_schema import PaginatedResponse, PaginationMeta
from app.schemas.dashboard.price_trend_schema import CompetitorPriceTrendPoint
from app.schemas.dashboard.recommendation_schema import (
    RecommendationListResponse,
    RecommendationRecord,
)
from app.schemas.dashboard.summary_schema import DashboardSummaryResponse, RealtimeActivityCounters

__all__ = [
    "AlertListResponse",
    "AlertRecord",
    "ActivityItem",
    "CompetitorListResponse",
    "CompetitorRecord",
    "DashboardErrorResponse",
    "ErrorDetail",
    "MarketTrendPoint",
    "OpportunityListResponse",
    "OpportunityRecord",
    "OpportunityMetricRecord",
    "PaginatedResponse",
    "PaginationMeta",
    "CompetitorPriceTrendPoint",
    "RecommendationListResponse",
    "RecommendationRecord",
    "DashboardSummaryResponse",
    "RealtimeActivityCounters",
]
