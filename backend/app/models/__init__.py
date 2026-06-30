from __future__ import annotations

from app.models.alert import Alert
from app.models.alert_delivery_log import AlertDeliveryLog
from app.models.competitor import Competitor
from app.models.competitor_event import CompetitorEvent, CompetitorEventSeverity, CompetitorEventType
from app.models.competitor_ranking import CompetitorRanking
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.inventory_history import InventoryHistory, InventorySnapshotSource
from app.models.inventory_risk import InventoryRiskAssessment, InventoryRiskDataStatus, InventoryRiskLevel
from app.models.market_opportunity import MarketOpportunity
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.recommendation import Recommendation
from app.models.reorder_recommendation import ReorderRecommendation, ReorderRecommendationAction, ReorderRecommendationStatus
from app.models.scrape_run import ScrapeRun
from app.models.sales_record import SalesRecord, SalesRecordStatus
from app.models.sales_velocity import SalesVelocity, SalesVelocityDataStatus
from app.models.seller import Seller
from app.models.stockout_prediction import StockoutPrediction, StockoutPredictionStatus
from app.models.telegram_connection import SellerTelegramConnection
from app.models.telegram_inventory_alert import TelegramInventoryAlert, TelegramInventoryAlertStatus, TelegramInventoryAlertType
from app.models.telegram_snapshot_log import TelegramProductSnapshotLog

__all__ = [
    "Alert",
    "AlertDeliveryLog",
    "Competitor",
    "CompetitorEvent",
    "CompetitorEventSeverity",
    "CompetitorEventType",
    "CompetitorRanking",
    "CompetitorSnapshot",
    "InventoryHistory",
    "InventoryRiskAssessment",
    "InventoryRiskDataStatus",
    "InventoryRiskLevel",
    "InventorySnapshotSource",
    "MarketOpportunity",
    "PriceHistory",
    "Product",
    "Recommendation",
    "ReorderRecommendation",
    "ReorderRecommendationAction",
    "ReorderRecommendationStatus",
    "ScrapeRun",
    "SalesRecord",
    "SalesRecordStatus",
    "SalesVelocity",
    "SalesVelocityDataStatus",
    "Seller",
    "StockoutPrediction",
    "StockoutPredictionStatus",
    "SellerTelegramConnection",
    "TelegramInventoryAlert",
    "TelegramInventoryAlertStatus",
    "TelegramInventoryAlertType",
    "TelegramProductSnapshotLog",
]
