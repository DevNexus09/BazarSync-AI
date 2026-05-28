from __future__ import annotations

from app.services.dashboard.alert_service import AlertDashboardService
from app.services.dashboard.competitor_service import CompetitorDashboardService
from app.services.dashboard.dashboard_service import DashboardService
from app.services.dashboard.opportunity_service import OpportunityDashboardService
from app.services.dashboard.recommendation_service import RecommendationDashboardService

__all__ = [
    "AlertDashboardService",
    "CompetitorDashboardService",
    "DashboardService",
    "OpportunityDashboardService",
    "RecommendationDashboardService",
]
