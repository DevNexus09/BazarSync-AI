from __future__ import annotations

from fastapi import APIRouter, FastAPI

from app.api.v1.alerts import router as alerts_router
from app.api.v1.auth import router as auth_router
from app.api.v1.competitors import router as competitors_router
from app.api.v1.competitor_events import router as competitor_events_router
from app.api.v1.competitor_dashboard import router as competitor_dashboard_router
from app.api.v1.competitor_rankings import router as competitor_rankings_router
from app.api.v1.copilot import router as copilot_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.dead_stock import router as dead_stock_router
from app.api.v1.dead_stock_capital_recovery import router as dead_stock_capital_recovery_router
from app.api.v1.dead_stock_dashboard import router as dead_stock_dashboard_router
from app.api.v1.dead_stock_recovery import router as dead_stock_recovery_router
from app.api.v1.dynamic_pricing import router as dynamic_pricing_router
from app.api.v1.health import router as health_router
from app.api.v1.inventory_risks import router as inventory_risks_router
from app.api.v1.inventory_intelligence import router as inventory_intelligence_router
from app.api.v1.inventory_aging import router as inventory_aging_router
from app.api.v1.inventory_setup import router as inventory_setup_router
from app.api.v1.market_opportunities import router as market_opportunities_router
from app.api.v1.products import router as products_router
from app.api.v1.product_visibility_metrics import router as product_visibility_metrics_router
from app.api.v1.pricing_analytics import router as pricing_analytics_router
from app.api.v1.pricing_overview import router as pricing_overview_router
from app.api.v1.pricing_policies import router as pricing_policies_router
from app.api.v1.rag import router as rag_router
from app.api.v1.revenue_simulator import router as revenue_simulator_router
from app.api.v1.recommendation_outcomes import router as recommendation_outcomes_router
from app.api.v1.recommendations import router as recommendations_router
from app.api.v1.reorder_recommendations import router as reorder_recommendations_router
from app.api.v1.sales_import import router as sales_import_router
from app.api.v1.scraper import router as scraper_router
from app.api.v1.scrape_runs import router as scrape_runs_router
from app.core.config import settings
from app.services.telegram.telegram_router import router as telegram_router
from app.api.v1.telegram_snapshot import router as telegram_snapshot_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(inventory_risks_router)
api_router.include_router(inventory_intelligence_router)
api_router.include_router(inventory_aging_router)
api_router.include_router(inventory_setup_router)
api_router.include_router(market_opportunities_router)
api_router.include_router(alerts_router)
api_router.include_router(auth_router)
api_router.include_router(competitors_router)
api_router.include_router(competitor_dashboard_router)
api_router.include_router(competitor_events_router)
api_router.include_router(competitor_rankings_router)
api_router.include_router(copilot_router)
api_router.include_router(dashboard_router)
api_router.include_router(dead_stock_router)
api_router.include_router(dead_stock_capital_recovery_router)
api_router.include_router(dead_stock_dashboard_router)
api_router.include_router(dead_stock_recovery_router)
api_router.include_router(dynamic_pricing_router)
api_router.include_router(products_router)
api_router.include_router(product_visibility_metrics_router)
api_router.include_router(pricing_analytics_router)
api_router.include_router(pricing_overview_router)
api_router.include_router(recommendation_outcomes_router)
api_router.include_router(pricing_policies_router)
api_router.include_router(rag_router)
api_router.include_router(revenue_simulator_router)
api_router.include_router(recommendations_router)
api_router.include_router(reorder_recommendations_router)
api_router.include_router(sales_import_router)
api_router.include_router(scraper_router)
api_router.include_router(scrape_runs_router)
api_router.include_router(telegram_router)
api_router.include_router(telegram_snapshot_router)


def register_routers(app: FastAPI) -> None:
    # Single registration point to keep route wiring predictable as modules grow.
    app.include_router(api_router, prefix=settings.api_v1_prefix)
