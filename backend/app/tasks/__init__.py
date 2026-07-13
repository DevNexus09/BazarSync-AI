from __future__ import annotations

from app.tasks import alert_tasks  # noqa: F401
from app.tasks import competitor_event_tasks  # noqa: F401
from app.tasks import competitor_ranking_tasks  # noqa: F401
from app.tasks import dead_stock_tasks  # noqa: F401
from app.tasks import dead_stock_workflow_tasks  # noqa: F401
from app.tasks import dead_stock_recovery_tasks  # noqa: F401
from app.tasks import inventory_history_tasks  # noqa: F401
from app.tasks import inventory_aging_tasks  # noqa: F401
from app.tasks import inventory_intelligence_workflow_tasks  # noqa: F401
from app.tasks import inventory_risk_tasks  # noqa: F401
from app.tasks import market_opportunity_tasks  # noqa: F401
from app.tasks import phase5_workflow_tasks  # noqa: F401
from app.tasks import pricing_analytics_tasks  # noqa: F401
from app.tasks import rag_memory_tasks  # noqa: F401
from app.tasks import recommendation_tasks  # noqa: F401
from app.tasks import reorder_recommendation_tasks  # noqa: F401
from app.tasks import sales_velocity_tasks  # noqa: F401
from app.tasks import scraper_tasks  # noqa: F401
from app.tasks import stockout_prediction_tasks  # noqa: F401
from app.tasks import telegram_inventory_alert_tasks  # noqa: F401
