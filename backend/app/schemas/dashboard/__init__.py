from __future__ import annotations

from app.schemas.dashboard.alert_schema import AlertListResponse, AlertRecord
from app.schemas.dashboard.competitor_schema import CompetitorListResponse, CompetitorRecord
from app.schemas.dashboard.error_schema import DashboardErrorResponse, ErrorDetail
from app.schemas.dashboard.opportunity_schema import OpportunityListResponse, OpportunityRecord
from app.schemas.dashboard.pagination_schema import PaginatedResponse, PaginationMeta
from app.schemas.dashboard.recommendation_schema import (
    RecommendationListResponse,
    RecommendationRecord,
)
from app.schemas.dashboard.summary_schema import DashboardSummaryResponse, RealtimeActivityCounters

__all__ = [
    "AlertListResponse",
    "AlertRecord",
    "CompetitorListResponse",
    "CompetitorRecord",
    "DashboardErrorResponse",
    "ErrorDetail",
    "OpportunityListResponse",
    "OpportunityRecord",
    "PaginatedResponse",
    "PaginationMeta",
    "RecommendationListResponse",
    "RecommendationRecord",
    "DashboardSummaryResponse",
    "RealtimeActivityCounters",
]
