from __future__ import annotations

from app.models.alert import Alert
from app.models.alert_delivery_log import AlertDeliveryLog
from app.models.competitor import Competitor
from app.models.competitor_event import CompetitorEvent, CompetitorEventSeverity, CompetitorEventType
from app.models.competitor_ranking import CompetitorRanking
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.demand_elasticity_estimate import DemandElasticityEstimate, DemandEstimateDataStatus, DemandEstimationMethod
from app.models.dead_stock_assessment import DeadStockAssessment, DeadStockClassification, DeadStockDataStatus, DeadStockInventoryAgeState, DeadStockNoSalesState, DeadStockVisibilityStatus
from app.models.dead_stock_capital_recovery import CapitalRecoveryEstimationMethod, CapitalRecoveryEstimateStatus, DeadStockCapitalRecoveryEstimate
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction, DeadStockRecoveryRecommendation, DeadStockRecoveryRecommendationStatus
from app.models.dynamic_pricing_recommendation import DynamicPricingAction, DynamicPricingRecommendation, DynamicPricingRecommendationStatus
from app.models.inventory_history import InventoryHistory, InventorySnapshotSource
from app.models.inventory_aging import InventoryAgeSource, InventoryAgingSnapshot
from app.models.inventory_stock_in import InventoryStockIn
from app.models.inventory_risk import InventoryRiskAssessment, InventoryRiskDataStatus, InventoryRiskLevel
from app.models.market_opportunity import MarketOpportunity
from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.price_history import PriceHistory
from app.models.pricing_policy import PricingObjective, PricingPolicy
from app.models.pricing_analytics_snapshot import PricingAnalyticsDataStatus, PricingAnalyticsSnapshot
from app.models.product import Product
from app.models.product_visibility_metric import ProductVisibilityMetric
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
    "DemandElasticityEstimate",
    "DemandEstimateDataStatus",
    "DemandEstimationMethod",
    "DeadStockAssessment",
    "DeadStockClassification",
    "DeadStockDataStatus",
    "DeadStockInventoryAgeState",
    "DeadStockNoSalesState",
    "DeadStockVisibilityStatus",
    "CapitalRecoveryEstimationMethod",
    "CapitalRecoveryEstimateStatus",
    "DeadStockCapitalRecoveryEstimate",
    "DeadStockRecoveryAction",
    "DeadStockRecoveryRecommendation",
    "DeadStockRecoveryRecommendationStatus",
    "DynamicPricingAction",
    "DynamicPricingRecommendation",
    "DynamicPricingRecommendationStatus",
    "InventoryHistory",
    "InventoryAgeSource",
    "InventoryAgingSnapshot",
    "InventoryStockIn",
    "InventoryRiskAssessment",
    "InventoryRiskDataStatus",
    "InventoryRiskLevel",
    "InventorySnapshotSource",
    "MarketOpportunity",
    "MarketplaceFeePolicy",
    "PriceHistory",
    "PricingObjective",
    "PricingAnalyticsDataStatus",
    "PricingAnalyticsSnapshot",
    "PricingPolicy",
    "Product",
    "ProductVisibilityMetric",
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
