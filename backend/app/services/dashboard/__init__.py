from __future__ import annotations

from app.services.dashboard.alert_service import AlertDashboardService
from app.services.dashboard.activity_service import ActivityDashboardService
from app.services.dashboard.competitor_service import CompetitorDashboardService
from app.services.dashboard.dashboard_service import DashboardService
from app.services.dashboard.market_trend_service import MarketTrendDashboardService
from app.services.dashboard.opportunity_metrics_service import OpportunityMetricsService
from app.services.dashboard.opportunity_service import OpportunityDashboardService
from app.services.dashboard.price_trend_service import CompetitorPriceTrendService
from app.services.dashboard.recommendation_service import RecommendationDashboardService

__all__ = [
    "AlertDashboardService",
    "ActivityDashboardService",
    "CompetitorDashboardService",
    "DashboardService",
    "MarketTrendDashboardService",
    "OpportunityMetricsService",
    "OpportunityDashboardService",
    "CompetitorPriceTrendService",
    "RecommendationDashboardService",
]
