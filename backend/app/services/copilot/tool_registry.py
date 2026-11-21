from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum
import logging
from typing import Any, Callable, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import case, func, inspect, select
from sqlalchemy.orm import Session, joinedload

from app.models.action_center_item import ActionCenterItem, ActionCenterItemStatus, ActionCenterPriority
from app.models.alert import Alert, AlertDeliveryStatus
from app.models.alert_delivery_log import AlertDeliveryLog
from app.models.competitor import Competitor
from app.models.competitor_event import CompetitorEvent
from app.models.competitor_ranking import CompetitorRanking
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.dead_stock_assessment import DeadStockAssessment
from app.models.dead_stock_capital_recovery import DeadStockCapitalRecoveryEstimate
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryRecommendation, DeadStockRecoveryRecommendationStatus
from app.models.demand_elasticity_estimate import DemandElasticityEstimate
from app.models.dynamic_pricing_recommendation import DynamicPricingRecommendation, DynamicPricingRecommendationStatus
from app.models.inventory_aging import InventoryAgingSnapshot
from app.models.inventory_history import InventoryHistory
from app.models.inventory_risk import InventoryRiskAssessment, InventoryRiskLevel
from app.models.inventory_stock_in import InventoryStockIn
from app.models.market_opportunity import MarketOpportunity, MarketOpportunityStatus
from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.price_history import PriceHistory
from app.models.pricing_analytics_snapshot import PricingAnalyticsSnapshot
from app.models.pricing_policy import PricingPolicy
from app.models.product import Product, ProductMarketplaceListing, ProductMarketplaceListingStatus, ProductStatus
from app.models.product_price_history import ProductPriceHistory
from app.models.product_visibility_metric import ProductVisibilityMetric
from app.models.promotion import PromotionPlan, PromotionPlanStatus, PromotionResult
from app.models.recommendation import Recommendation
from app.models.reorder_recommendation import ReorderRecommendation, ReorderRecommendationAction, ReorderRecommendationStatus
from app.models.rag_memory import RagMemoryChunk, RagMemoryDocument, RagMemoryEmbeddingStatus, RagMemorySourceType
from app.models.sales_record import SalesRecord, SalesRecordStatus
from app.models.sales_velocity import SalesVelocity
from app.models.scrape_run import ScrapeRun
from app.models.stockout_prediction import StockoutPrediction
from app.models.telegram_connection import SellerTelegramConnection
from app.models.telegram_snapshot_log import TelegramProductSnapshotLog
from app.services.copilot.business_change_analytics_service import BusinessChangeAnalyticsService
from app.services.copilot.business_data_catalog import BusinessDataCatalogService
from app.services.copilot.metric_catalog import MetricCatalogService
from app.services.copilot.metric_execution_service import MetricExecutionService
from app.services.copilot.profit_margin_analytics_service import ProfitMarginAnalyticsService
from app.services.copilot.query_constraints import BusinessDomainKey
from app.services.copilot.sales_revenue_analytics_service import SalesRevenueAnalyticsService
from app.services.rag_observability import elapsed_ms, log_event, now_ms, observe_latency
from app.services.rag_retrieval_service import RagRetrievalService


logger = logging.getLogger(__name__)

MAX_LIMIT = 25
MAX_TOP_K = 20
DEFAULT_TOOL_RUNTIME_MS = 2500


class CopilotToolSafetyLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    PROPOSE_ACTION = "PROPOSE_ACTION"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    EXECUTION_DISABLED = "EXECUTION_DISABLED"


class ToolExecutionStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ToolArgumentError(ValueError):
    pass


class ProductAccessError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class CopilotToolContext:
    seller_id: UUID
    db: Session | None = None
    user_id: UUID | None = None
    language: str = "en"
    request_id: str | None = None
    read_only: bool = True


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    version: str
    description: str
    argument_schema: type[BaseModel]
    return_schema: dict[str, Any]
    safety_level: CopilotToolSafetyLevel
    requires_confirmation: bool
    allowed_in_read_only_mode: bool
    max_runtime_ms: int
    implementation: Callable[[CopilotToolContext, dict[str, Any]], dict[str, Any]]
    seller_ownership_checks: tuple[str, ...]
    error_handling_behavior: str
    catalog_domains: tuple[str, ...] = ()
    catalog_metrics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    tool_name: str
    tool_version: str
    status: ToolExecutionStatus
    data: dict[str, Any]
    evidence: list[dict[str, Any]]
    missing_data: list[str]
    error: dict[str, Any] | None
    runtime_ms: int


@dataclass(frozen=True, slots=True)
class SourceToolSpec:
    name: str
    domain: BusinessDomainKey
    description: str
    model: Any
    source_table: str
    date_field: str | None = None
    seller_field: str | None = "seller_id"
    product_field: str | None = "product_id"
    competitor_field: str | None = None
    join_product_for_seller: bool = False
    join_competitor_for_seller: bool = False
    safe_fields: tuple[str, ...] = ()


class _BaseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _LimitArgs(_BaseArgs):
    product_id: UUID | None = None
    limit: int = Field(default=10, ge=1, le=MAX_LIMIT)


class SourceQueryArgs(_BaseArgs):
    query: str | None = Field(default=None, min_length=1, max_length=500)
    product_id: UUID | None = None
    competitor_id: UUID | None = None
    from_date: date | None = None
    to_date: date | None = None
    category: str | None = Field(default=None, max_length=120)
    marketplace: str | None = Field(default=None, max_length=120)
    risk_level: str | None = Field(default=None, max_length=40)
    event_type: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, max_length=120)
    limit: int = Field(default=10, ge=1, le=MAX_LIMIT)
    offset: int = Field(default=0, ge=0)

    @field_validator("risk_level", "event_type", "status")
    @classmethod
    def normalize_enums(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @model_validator(mode="after")
    def validate_range(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class TodayActionsArgs(_LimitArgs):
    pass


class RestockRecommendationsArgs(_LimitArgs):
    category: str | None = Field(default=None, max_length=120)


class InventoryRisksArgs(_LimitArgs):
    risk_level: str | None = Field(default=None, max_length=20)

    @field_validator("risk_level")
    @classmethod
    def normalize_risk_level(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @model_validator(mode="after")
    def validate_risk_level(self):
        if self.risk_level and self.risk_level not in {item.value for item in InventoryRiskLevel}:
            raise ValueError("risk_level must be LOW, MEDIUM, HIGH, or CRITICAL")
        return self


class RevenueDropArgs(_BaseArgs):
    product_id: UUID | None = None
    from_date: date
    to_date: date
    compare_to_previous_period: bool = True

    @model_validator(mode="after")
    def validate_range(self):
        if self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class RevenueSummaryArgs(_BaseArgs):
    product_id: UUID | None = None
    from_date: date
    to_date: date
    marketplace: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=120)
    compare_to_previous_period: bool = True

    @model_validator(mode="after")
    def validate_range(self):
        if self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class SalesTrendsArgs(_BaseArgs):
    product_id: UUID | None = None
    from_date: date
    to_date: date
    granularity: str = Field(default="daily", max_length=20)
    marketplace: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_values(self):
        if self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        if self.granularity not in {"daily", "weekly", "monthly"}:
            raise ValueError("granularity must be daily, weekly, or monthly")
        return self


class ProfitSummaryArgs(_BaseArgs):
    product_id: UUID | None = None
    from_date: date
    to_date: date
    marketplace: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_range(self):
        if self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class TopProductsByRevenueArgs(_BaseArgs):
    from_date: date
    to_date: date
    limit: int = Field(default=10, ge=1, le=MAX_LIMIT)
    category: str | None = Field(default=None, max_length=120)
    marketplace: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_range(self):
        if self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class ProductsWithNoSalesArgs(_BaseArgs):
    since_date: date | None = None
    category: str | None = Field(default=None, max_length=120)
    marketplace: str | None = Field(default=None, max_length=120)
    limit: int = Field(default=10, ge=1, le=MAX_LIMIT)
    offset: int = Field(default=0, ge=0)


class CompetitorThreatsArgs(_LimitArgs):
    from_date: date | None = None
    to_date: date | None = None

    @model_validator(mode="after")
    def validate_range(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class PricingRecommendationsArgs(_LimitArgs):
    pass


class SimulatePriceChangeArgs(_BaseArgs):
    product_id: UUID
    candidate_price: Decimal | None = Field(default=None, ge=0)
    candidate_discount_rate: Decimal | None = Field(default=None, ge=0, lt=1)
    forecast_horizon_days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def validate_candidate(self):
        if self.candidate_price is None and self.candidate_discount_rate is None:
            raise ValueError("candidate_price or candidate_discount_rate is required")
        return self


class PromotionRecommendationsArgs(_LimitArgs):
    category: str | None = Field(default=None, max_length=120)


class PromotionRecordsArgs(_LimitArgs):
    status: str | None = Field(default=None, max_length=80)
    marketplace: str | None = Field(default=None, max_length=120)
    from_date: date | None = None
    to_date: date | None = None
    offset: int = Field(default=0, ge=0)

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @model_validator(mode="after")
    def validate_range(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class PriceHistoryArgs(_LimitArgs):
    marketplace: str | None = Field(default=None, max_length=120)
    from_date: date | None = None
    to_date: date | None = None
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_range(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class DeadStockRecoveryArgs(_LimitArgs):
    pass


class SeoOpportunitiesArgs(_LimitArgs):
    pass


class RetrieveBusinessMemoryArgs(_BaseArgs):
    question: str = Field(min_length=1, max_length=2000)
    product_id: UUID | None = None
    source_types: list[str] | None = None
    from_date: date | None = None
    to_date: date | None = None
    top_k: int = Field(default=8, ge=1, le=MAX_TOP_K)

    @field_validator("source_types")
    @classmethod
    def normalize_source_types(cls, value: list[str] | None) -> list[str] | None:
        return [item.upper() for item in value] if value else None

    @model_validator(mode="after")
    def validate_range(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class SellerMetricQueryArgs(_BaseArgs):
    metric_key: str = Field(min_length=1, max_length=120)
    filters: dict[str, Any] = Field(default_factory=dict)
    group_by: list[str] | None = None
    from_date: date | None = None
    to_date: date | None = None
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_range(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class ProductFilterArgs(_BaseArgs):
    status: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=120)
    marketplace: str | None = Field(default=None, max_length=120)
    has_stock: bool | None = None
    missing_cost: bool | None = None
    missing_fee_policy: bool | None = None
    missing_pricing_policy: bool | None = None
    missing_sales: bool | None = None

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class BusinessOverviewArgs(_BaseArgs):
    from_date: date | None = None
    to_date: date | None = None
    marketplace: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_range(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class SummaryArgs(_BaseArgs):
    product_id: UUID | None = None
    from_date: date | None = None
    to_date: date | None = None
    marketplace: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=120)
    limit: int = Field(default=5, ge=1, le=MAX_LIMIT)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_range(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class CountProductsArgs(ProductFilterArgs):
    pass


class ListProductsArgs(ProductFilterArgs):
    sort_by: str | None = Field(default="created_at_desc", max_length=40)
    limit: int = Field(default=10, ge=1, le=MAX_LIMIT)
    offset: int = Field(default=0, ge=0)

    @field_validator("sort_by")
    @classmethod
    def validate_sort_by(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in {"created_at_desc", "created_at_asc", "title_asc", "title_desc", "stock_desc", "stock_asc", "price_desc", "price_asc"}:
            raise ValueError("sort_by is not supported")
        return value


class SearchProductsArgs(_BaseArgs):
    query: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=120)
    marketplace: str | None = Field(default=None, max_length=120)
    limit: int = Field(default=10, ge=1, le=MAX_LIMIT)


class ProductProfileArgs(_BaseArgs):
    product_id: UUID


class MissingSetupType(str, Enum):
    COST = "COST"
    SELLING_PRICE = "SELLING_PRICE"
    MARKETPLACE_FEE_POLICY = "MARKETPLACE_FEE_POLICY"
    PRICING_POLICY = "PRICING_POLICY"
    INVENTORY_AGE_SOURCE = "INVENTORY_AGE_SOURCE"
    SALES_HISTORY = "SALES_HISTORY"
    VISIBILITY_DATA = "VISIBILITY_DATA"


class ProductsMissingSetupArgs(_BaseArgs):
    setup_type: MissingSetupType | None = None
    category: str | None = Field(default=None, max_length=120)
    marketplace: str | None = Field(default=None, max_length=120)
    limit: int = Field(default=10, ge=1, le=MAX_LIMIT)
    offset: int = Field(default=0, ge=0)


SOURCE_TOOL_SPECS: dict[str, SourceToolSpec] = {
    "get_inventory_summary": SourceToolSpec("get_inventory_summary", BusinessDomainKey.INVENTORY, "Return recent seller inventory source rows and freshness across stock, aging, velocity, and risk data.", InventoryHistory, "inventory_history", "captured_at"),
    "get_inventory_history": SourceToolSpec("get_inventory_history", BusinessDomainKey.INVENTORY, "Return seller inventory snapshots.", InventoryHistory, "inventory_history", "captured_at"),
    "get_stock_in_history": SourceToolSpec("get_stock_in_history", BusinessDomainKey.INVENTORY, "Return seller stock-in records.", InventoryStockIn, "inventory_stock_in", "received_at"),
    "get_inventory_aging": SourceToolSpec("get_inventory_aging", BusinessDomainKey.INVENTORY, "Return seller inventory aging snapshots.", InventoryAgingSnapshot, "inventory_aging_snapshots", "calculated_at"),
    "get_sales_velocity": SourceToolSpec("get_sales_velocity", BusinessDomainKey.INVENTORY, "Return direct seller sales velocity calculations.", SalesVelocity, "sales_velocity", "calculated_at"),
    "get_stockout_predictions": SourceToolSpec("get_stockout_predictions", BusinessDomainKey.INVENTORY, "Return seller stockout predictions.", StockoutPrediction, "stockout_predictions", "calculated_at", safe_fields=("id", "product_id", "as_of_date", "quantity_on_hand", "quantity_reserved", "quantity_incoming", "inventory_position", "daily_sales_rate", "days_remaining", "predicted_stockout_date", "prediction_status", "confidence_score", "calculated_at", "created_at")),
    "get_reorder_recommendations": SourceToolSpec("get_reorder_recommendations", BusinessDomainKey.INVENTORY, "Return seller reorder recommendations.", ReorderRecommendation, "reorder_recommendations", "generated_at"),
    "get_products_low_stock": SourceToolSpec("get_products_low_stock", BusinessDomainKey.INVENTORY, "Return products with low-stock or reorder signals.", ReorderRecommendation, "reorder_recommendations", "generated_at"),
    "get_products_overstocked": SourceToolSpec("get_products_overstocked", BusinessDomainKey.INVENTORY, "Return products with dead-stock or overstock signals.", DeadStockAssessment, "dead_stock_assessments", "assessed_at"),
    "get_pricing_summary": SourceToolSpec("get_pricing_summary", BusinessDomainKey.PRICING, "Return recent seller pricing analytics and freshness.", PricingAnalyticsSnapshot, "pricing_analytics_snapshots", "calculated_at"),
    "get_pricing_policy": SourceToolSpec("get_pricing_policy", BusinessDomainKey.PRICING, "Return seller pricing policies.", PricingPolicy, "pricing_policies", "effective_from"),
    "get_fee_policy": SourceToolSpec("get_fee_policy", BusinessDomainKey.PROFIT_MARGIN, "Return seller marketplace fee policies.", MarketplaceFeePolicy, "marketplace_fee_policies", "effective_from", product_field="product_id"),
    "get_products_missing_pricing_setup": SourceToolSpec("get_products_missing_pricing_setup", BusinessDomainKey.PRICING, "Return products missing pricing or fee policy setup.", Product, "products", "created_at"),
    "get_pricing_analytics": SourceToolSpec("get_pricing_analytics", BusinessDomainKey.PRICING, "Return seller pricing analytics snapshots.", PricingAnalyticsSnapshot, "pricing_analytics_snapshots", "calculated_at"),
    "get_elasticity_estimates": SourceToolSpec("get_elasticity_estimates", BusinessDomainKey.PRICING, "Return seller demand elasticity estimates.", DemandElasticityEstimate, "demand_elasticity_estimates", "calculated_at"),
    "get_price_history": SourceToolSpec("get_price_history", BusinessDomainKey.PRICING, "Return seller-side product/listing price change history.", ProductPriceHistory, "product_price_history", "changed_at"),
    "get_margin_safety": SourceToolSpec("get_margin_safety", BusinessDomainKey.PROFIT_MARGIN, "Return persisted MarginGuard pricing safety snapshots.", PricingAnalyticsSnapshot, "pricing_analytics_snapshots", "calculated_at", safe_fields=("id", "product_id", "current_price", "unit_cost", "percentage_fee_rate", "fixed_fee_amount", "current_unit_profit", "current_margin_rate", "minimum_safe_price", "data_status", "confidence_score", "calculated_at", "created_at")),
    "get_competitor_summary": SourceToolSpec("get_competitor_summary", BusinessDomainKey.COMPETITOR, "Return recent competitor records for seller-owned products.", Competitor, "competitors", "updated_at", seller_field=None, join_product_for_seller=True, competitor_field="id"),
    "get_competitor_events": SourceToolSpec("get_competitor_events", BusinessDomainKey.COMPETITOR, "Return seller competitor events.", CompetitorEvent, "competitor_events", "detected_at", competitor_field="competitor_id"),
    "get_competitor_snapshots": SourceToolSpec("get_competitor_snapshots", BusinessDomainKey.COMPETITOR, "Return competitor snapshots for seller-owned products.", CompetitorSnapshot, "competitor_snapshots", "captured_at", seller_field=None, join_product_for_seller=True, competitor_field="competitor_id"),
    "get_competitor_price_history": SourceToolSpec("get_competitor_price_history", BusinessDomainKey.COMPETITOR, "Return competitor price history for seller-owned products.", PriceHistory, "price_history", "observed_at", seller_field=None, product_field=None, competitor_field="competitor_id", join_competitor_for_seller=True),
    "get_competitor_rankings": SourceToolSpec("get_competitor_rankings", BusinessDomainKey.COMPETITOR, "Return seller competitor ranking history.", CompetitorRanking, "competitor_rankings", "calculated_at", competitor_field="competitor_id"),
    "get_market_opportunities": SourceToolSpec("get_market_opportunities", BusinessDomainKey.COMPETITOR, "Return seller market opportunities.", MarketOpportunity, "market_opportunities", "detected_at", competitor_field="competitor_id"),
    "get_scrape_run_summary": SourceToolSpec("get_scrape_run_summary", BusinessDomainKey.COMPETITOR, "Return seller scrape run history and freshness.", ScrapeRun, "scrape_runs", "created_at"),
    "compare_product_against_competitors": SourceToolSpec("compare_product_against_competitors", BusinessDomainKey.COMPETITOR, "Return competitor snapshots for comparing a seller product against competitors.", CompetitorSnapshot, "competitor_snapshots", "captured_at", seller_field=None, join_product_for_seller=True, competitor_field="competitor_id"),
    "get_dead_stock_summary": SourceToolSpec("get_dead_stock_summary", BusinessDomainKey.DEAD_STOCK, "Return seller dead-stock assessment summary rows.", DeadStockAssessment, "dead_stock_assessments", "assessed_at"),
    "get_dead_stock_assessments": SourceToolSpec("get_dead_stock_assessments", BusinessDomainKey.DEAD_STOCK, "Return seller dead-stock assessments.", DeadStockAssessment, "dead_stock_assessments", "assessed_at"),
    "get_dead_stock_products": SourceToolSpec("get_dead_stock_products", BusinessDomainKey.DEAD_STOCK, "Return products with dead-stock assessment signals.", DeadStockAssessment, "dead_stock_assessments", "assessed_at"),
    "get_capital_recovery_estimates": SourceToolSpec("get_capital_recovery_estimates", BusinessDomainKey.DEAD_STOCK, "Return persisted dead-stock capital recovery estimates.", DeadStockCapitalRecoveryEstimate, "dead_stock_capital_recovery_estimates", "calculated_at"),
    "get_capital_recovery_summary": SourceToolSpec("get_capital_recovery_summary", BusinessDomainKey.DEAD_STOCK, "Return persisted capital recovery estimates and freshness.", DeadStockCapitalRecoveryEstimate, "dead_stock_capital_recovery_estimates", "calculated_at"),
    "get_visibility_summary": SourceToolSpec("get_visibility_summary", BusinessDomainKey.SEO_VISIBILITY, "Return recent visibility metric rows and freshness.", ProductVisibilityMetric, "product_visibility_metrics", "metric_date"),
    "get_visibility_history": SourceToolSpec("get_visibility_history", BusinessDomainKey.SEO_VISIBILITY, "Return seller product visibility history.", ProductVisibilityMetric, "product_visibility_metrics", "metric_date"),
    "get_listing_quality_issues": SourceToolSpec("get_listing_quality_issues", BusinessDomainKey.SEO_VISIBILITY, "Return listing quality metric rows that can support SEO findings.", ProductVisibilityMetric, "product_visibility_metrics", "metric_date"),
    "get_alert_summary": SourceToolSpec("get_alert_summary", BusinessDomainKey.ALERTS, "Return recent seller alert rows and freshness.", Alert, "alerts", "created_at"),
    "get_recent_alerts": SourceToolSpec("get_recent_alerts", BusinessDomainKey.ALERTS, "Return recent seller alerts.", Alert, "alerts", "created_at"),
    "get_alert_delivery_history": SourceToolSpec("get_alert_delivery_history", BusinessDomainKey.ALERTS, "Return seller alert delivery history.", AlertDeliveryLog, "alert_delivery_logs", "sent_at", product_field=None),
    "get_unresolved_alerts": SourceToolSpec("get_unresolved_alerts", BusinessDomainKey.ALERTS, "Return pending or undelivered seller alerts.", Alert, "alerts", "created_at"),
    "get_telegram_connection_status": SourceToolSpec("get_telegram_connection_status", BusinessDomainKey.ALERTS, "Return safe seller Telegram connection status without tokens or chat identifiers.", SellerTelegramConnection, "seller_telegram_connections", "updated_at", product_field=None, safe_fields=("id", "seller_id", "telegram_username", "telegram_first_name", "telegram_last_name", "is_connected", "connected_at", "last_alert_sent_at", "created_at", "updated_at")),
    "get_snapshot_delivery_history": SourceToolSpec("get_snapshot_delivery_history", BusinessDomainKey.ALERTS, "Return Telegram product snapshot delivery history without chat identifiers.", TelegramProductSnapshotLog, "snapshot_logs", "sent_at", safe_fields=("id", "seller_id", "product_id", "sent_at", "status")),
    "get_recommendation_summary": SourceToolSpec("get_recommendation_summary", BusinessDomainKey.RECOMMENDATIONS, "Return recent raw recommendation rows and freshness.", Recommendation, "recommendations", "created_at", seller_field=None, join_product_for_seller=True),
    "get_recommendation_history": SourceToolSpec("get_recommendation_history", BusinessDomainKey.RECOMMENDATIONS, "Return seller raw recommendation history.", Recommendation, "recommendations", "created_at", seller_field=None, join_product_for_seller=True),
    "get_pending_recommendations": SourceToolSpec("get_pending_recommendations", BusinessDomainKey.RECOMMENDATIONS, "Return pending/open recommendations from recommendation engines.", DynamicPricingRecommendation, "dynamic_pricing_recommendations", "generated_at"),
    "get_ignored_recommendations": SourceToolSpec("get_ignored_recommendations", BusinessDomainKey.RECOMMENDATIONS, "Return dismissed/ignored recommendations where persisted.", DynamicPricingRecommendation, "dynamic_pricing_recommendations", "generated_at"),
    "search_business_memory": SourceToolSpec("search_business_memory", BusinessDomainKey.RAG_MEMORY, "Search seller-scoped RAG business memory.", RagMemoryChunk, "rag_memory_chunks", "event_time", safe_fields=("id", "memory_document_id", "product_id", "source_type", "chunk_index", "chunk_text", "token_estimate", "metadata_json", "event_time", "embedding_status", "embedded_at", "created_at")),
    "get_memory_coverage_status": SourceToolSpec("get_memory_coverage_status", BusinessDomainKey.RAG_MEMORY, "Return seller memory coverage status.", RagMemoryDocument, "rag_memory_documents", "event_time", safe_fields=("id", "product_id", "source_type", "source_table", "source_id", "source_version", "title", "summary_text", "language", "metadata_json", "sensitivity_level", "visibility_scope", "event_time", "created_at", "updated_at", "embedding_status")),
}


class CopilotToolDataAccess(Protocol):
    def verify_product_owned(self, *, seller_id: UUID, product_id: UUID) -> bool: ...
    def get_business_overview(self, *, seller_id: UUID, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None) -> tuple[dict[str, Any], list[str]]: ...
    def count_products(self, *, seller_id: UUID, filters: dict[str, Any]) -> tuple[dict[str, Any], list[str]]: ...
    def list_products(self, *, seller_id: UUID, filters: dict[str, Any], sort_by: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def search_products(self, *, seller_id: UUID, query: str, category: str | None, marketplace: str | None, limit: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_product_profile(self, *, seller_id: UUID, product_id: UUID) -> tuple[dict[str, Any], list[str]]: ...
    def get_products_missing_setup(self, *, seller_id: UUID, setup_type: str | None, category: str | None, marketplace: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_inventory_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_sales_velocity_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_stockout_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_reorder_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_inventory_aging_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_competitor_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_competitor_price_change_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_competitor_undercut_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_market_opportunity_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_scrape_health_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_pricing_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_fee_policy_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_pricing_policy_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_elasticity_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_seller_price_history_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_promotion_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_promotion_outcome_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_alert_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_recommendation_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_revenue_summary(self, *, seller_id: UUID, from_date: date, to_date: date, marketplace: str | None, product_id: UUID | None, category: str | None, compare_to_previous_period: bool) -> tuple[dict[str, Any], list[str]]: ...
    def get_sales_trends(self, *, seller_id: UUID, from_date: date, to_date: date, granularity: str, marketplace: str | None, product_id: UUID | None, category: str | None) -> tuple[dict[str, Any], list[str]]: ...
    def get_profit_summary(self, *, seller_id: UUID, from_date: date, to_date: date, marketplace: str | None, product_id: UUID | None, category: str | None) -> tuple[dict[str, Any], list[str]]: ...
    def explain_revenue_change_deterministic(self, *, seller_id: UUID, from_date: date, to_date: date, compare_to_previous_period: bool, marketplace: str | None, product_id: UUID | None, category: str | None) -> tuple[dict[str, Any], list[str]]: ...
    def get_top_products_by_revenue(self, *, seller_id: UUID, from_date: date, to_date: date, limit: int, category: str | None, marketplace: str | None) -> tuple[dict[str, Any], list[str]]: ...
    def get_products_with_no_sales(self, *, seller_id: UUID, since_date: date | None, category: str | None, marketplace: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_today_actions(self, *, seller_id: UUID, product_id: UUID | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]: ...
    def get_restock_recommendations(self, *, seller_id: UUID, product_id: UUID | None, category: str | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]: ...
    def get_inventory_risks(self, *, seller_id: UUID, product_id: UUID | None, risk_level: str | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]: ...
    def explain_revenue_drop(self, *, seller_id: UUID, product_id: UUID | None, from_date: date, to_date: date, compare_to_previous_period: bool) -> tuple[dict[str, Any], list[str]]: ...
    def get_competitor_threats(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]: ...
    def get_pricing_recommendations(self, *, seller_id: UUID, product_id: UUID | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]: ...
    def simulate_price_change(self, *, seller_id: UUID, product_id: UUID, candidate_price: Decimal | None, candidate_discount_rate: Decimal | None, forecast_horizon_days: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_promotion_plans(self, *, seller_id: UUID, product_id: UUID | None, status: str | None, marketplace: str | None, from_date: date | None, to_date: date | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_promotion_results(self, *, seller_id: UUID, product_id: UUID | None, status: str | None, marketplace: str | None, from_date: date | None, to_date: date | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def compare_promotion_performance(self, *, seller_id: UUID, product_id: UUID | None, marketplace: str | None, from_date: date | None, to_date: date | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_price_history(self, *, seller_id: UUID, product_id: UUID | None, marketplace: str | None, from_date: date | None, to_date: date | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_products_with_recent_price_changes(self, *, seller_id: UUID, product_id: UUID | None, marketplace: str | None, from_date: date | None, to_date: date | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_promotion_recommendations(self, *, seller_id: UUID, product_id: UUID | None, category: str | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]: ...
    def get_dead_stock_recovery(self, *, seller_id: UUID, product_id: UUID | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]: ...
    def get_seo_opportunities(self, *, seller_id: UUID, product_id: UUID | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]: ...
    def retrieve_business_memory(self, *, seller_id: UUID, question: str, product_id: UUID | None, source_types: list[str] | None, from_date: date | None, to_date: date | None, top_k: int) -> tuple[dict[str, Any], list[str]]: ...
    def get_business_source(self, *, seller_id: UUID, spec: SourceToolSpec, filters: dict[str, Any], limit: int, offset: int) -> tuple[dict[str, Any], list[str]]: ...


class CopilotToolRegistry:
    def __init__(
        self,
        data_access: CopilotToolDataAccess | None = None,
        *,
        business_catalog: BusinessDataCatalogService | None = None,
        metric_catalog: MetricCatalogService | None = None,
    ) -> None:
        self._data_access = data_access
        self._business_catalog = business_catalog or BusinessDataCatalogService()
        self._metric_catalog = metric_catalog or MetricCatalogService()
        self._tools: dict[str, ToolDefinition] = {}
        self._register_read_only_tools()

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Copilot tool is not allowlisted: {name}") from exc

    def validate_arguments(self, name: str, arguments: dict[str, Any]) -> tuple[bool, dict[str, Any] | None, str | None]:
        try:
            tool = self.get_tool(name)
            return True, tool.argument_schema.model_validate(arguments).model_dump(), None
        except KeyError as exc:
            return False, None, str(exc)
        except ValidationError as exc:
            return False, None, _validation_message(exc)

    def execute(self, *, name: str, context: CopilotToolContext, arguments: dict[str, Any]) -> ToolExecutionResult:
        start_ms = now_ms()
        try:
            tool = self.get_tool(name)
        except KeyError as exc:
            return self._error_result(name=name, version="unknown", status=ToolExecutionStatus.BLOCKED, code="TOOL_NOT_ALLOWLISTED", message=str(exc), start_ms=start_ms)

        if context.read_only and not tool.allowed_in_read_only_mode:
            return self._error_result(name=name, version=tool.version, status=ToolExecutionStatus.BLOCKED, code="READ_ONLY_MODE", message="Tool is not allowed in read-only mode.", start_ms=start_ms)

        try:
            parsed = tool.argument_schema.model_validate(arguments).model_dump()
            product_id = parsed.get("product_id")
            if product_id is not None and not self._data(context).verify_product_owned(seller_id=context.seller_id, product_id=product_id):
                raise ProductAccessError("Product does not belong to the authenticated seller.")
            data = _normalize_tool_payload(tool.implementation(context, parsed), tool=tool)
            evidence = _extract_evidence(data)
            missing_data = list(data.get("missing_data", []))
            runtime_ms = elapsed_ms(start_ms)
            observe_latency("copilot_tool_runtime_ms", runtime_ms)
            if runtime_ms > tool.max_runtime_ms:
                return self._error_result(
                    name=name,
                    version=tool.version,
                    status=ToolExecutionStatus.FAILED,
                    code="TOOL_TIMEOUT",
                    message="The tool exceeded its safe runtime budget.",
                    start_ms=start_ms,
                    context=context,
                    tool=tool,
                )
            self._log(context=context, tool=tool, status=ToolExecutionStatus.SUCCEEDED, runtime_ms=runtime_ms, evidence_count=len(evidence))
            return ToolExecutionResult(
                tool_name=tool.name,
                tool_version=tool.version,
                status=ToolExecutionStatus.SUCCEEDED,
                data=_json_safe(data),
                evidence=_json_safe(evidence),
                missing_data=missing_data,
                error=None,
                runtime_ms=runtime_ms,
            )
        except ValidationError as exc:
            return self._error_result(name=name, version=tool.version, status=ToolExecutionStatus.BLOCKED, code="INVALID_ARGUMENTS", message=_validation_message(exc), start_ms=start_ms, context=context, tool=tool)
        except ProductAccessError as exc:
            return self._error_result(name=name, version=tool.version, status=ToolExecutionStatus.BLOCKED, code="PRODUCT_ACCESS_DENIED", message=str(exc), start_ms=start_ms, context=context, tool=tool)
        except ToolArgumentError as exc:
            return self._error_result(name=name, version=tool.version, status=ToolExecutionStatus.BLOCKED, code="INVALID_ARGUMENTS", message=str(exc), start_ms=start_ms, context=context, tool=tool)
        except Exception:
            if context.db is not None:
                context.db.rollback()
            logger.exception("copilot_tool_failed tool_name=%s seller_id=%s", name, context.seller_id)
            return self._error_result(name=name, version=tool.version, status=ToolExecutionStatus.FAILED, code="TOOL_FAILED", message="The tool could not complete safely.", start_ms=start_ms, context=context, tool=tool)

    def _data(self, context: CopilotToolContext) -> CopilotToolDataAccess:
        if self._data_access is not None:
            return self._data_access
        if context.db is None:
            raise RuntimeError("Copilot tool execution requires a database session or injected data access.")
        return SqlAlchemyCopilotToolDataAccess(context.db)

    def _register_read_only_tools(self) -> None:
        self._register("get_business_overview", BusinessOverviewArgs, "Return a seller-scoped business setup, freshness, product, revenue, risk, alert, and recommendation overview.", self._get_business_overview, domains=(BusinessDomainKey.PRODUCT_CATALOG, BusinessDomainKey.SALES_REVENUE, BusinessDomainKey.PROFIT_MARGIN, BusinessDomainKey.INVENTORY, BusinessDomainKey.ALERTS, BusinessDomainKey.RECOMMENDATIONS), metrics=("product_count", "active_product_count", "products_missing_cost_count", "products_missing_fee_policy_count", "products_with_stock_count", "products_with_no_sales_count", "gross_revenue", "estimated_profit", "stockout_risk_count", "dead_stock_count", "pending_recommendation_count", "unresolved_alert_count"))
        self._register("get_product_setup_summary", SummaryArgs, "Return seller-scoped aggregate product listing and setup summary.", self._get_product_setup_summary, domains=(BusinessDomainKey.PRODUCT_CATALOG, BusinessDomainKey.PRICING, BusinessDomainKey.PROFIT_MARGIN), metrics=("product_count", "active_product_count", "listed_product_count", "products_missing_cost_count", "products_missing_fee_policy_count", "products_missing_pricing_policy_count"))
        self._register("get_inventory_summary", SummaryArgs, "Return seller-scoped aggregate inventory summary.", self._get_inventory_summary, domains=(BusinessDomainKey.INVENTORY,), metrics=("products_with_stock_count", "current_inventory_value", "low_stock_product_count", "stockout_risk_count", "dead_stock_count"))
        self._register("get_sales_velocity_summary", SummaryArgs, "Return seller-scoped aggregate sales velocity summary.", self._get_sales_velocity_summary, domains=(BusinessDomainKey.INVENTORY, BusinessDomainKey.SALES_REVENUE))
        self._register("get_stockout_summary", SummaryArgs, "Return seller-scoped aggregate stockout prediction summary.", self._get_stockout_summary, domains=(BusinessDomainKey.INVENTORY,), metrics=("stockout_risk_count",))
        self._register("get_reorder_summary", SummaryArgs, "Return seller-scoped aggregate reorder recommendation summary.", self._get_reorder_summary, domains=(BusinessDomainKey.INVENTORY, BusinessDomainKey.RECOMMENDATIONS), metrics=("low_stock_product_count",))
        self._register("get_inventory_aging_summary", SummaryArgs, "Return seller-scoped aggregate inventory aging summary.", self._get_inventory_aging_summary, domains=(BusinessDomainKey.INVENTORY, BusinessDomainKey.DEAD_STOCK))
        self._register("get_competitor_summary", SummaryArgs, "Return seller-scoped aggregate competitor summary.", self._get_competitor_summary, domains=(BusinessDomainKey.COMPETITOR,), metrics=("competitor_undercut_count", "competitor_price_gap"))
        self._register("get_competitor_price_change_summary", SummaryArgs, "Return seller-scoped aggregate competitor price-change summary.", self._get_competitor_price_change_summary, domains=(BusinessDomainKey.COMPETITOR,), metrics=("competitor_price_gap",))
        self._register("get_competitor_undercut_summary", SummaryArgs, "Return seller-scoped aggregate competitor undercut summary.", self._get_competitor_undercut_summary, domains=(BusinessDomainKey.COMPETITOR,), metrics=("competitor_undercut_count",))
        self._register("get_market_opportunity_summary", SummaryArgs, "Return seller-scoped aggregate market opportunity summary.", self._get_market_opportunity_summary, domains=(BusinessDomainKey.COMPETITOR, BusinessDomainKey.RECOMMENDATIONS))
        self._register("get_scrape_health_summary", SummaryArgs, "Return seller-scoped aggregate scrape-run health summary.", self._get_scrape_health_summary, domains=(BusinessDomainKey.COMPETITOR,))
        self._register("get_pricing_summary", SummaryArgs, "Return seller-scoped aggregate pricing setup and recommendation summary.", self._get_pricing_summary, domains=(BusinessDomainKey.PRICING, BusinessDomainKey.PROFIT_MARGIN), metrics=("products_missing_fee_policy_count", "products_missing_pricing_policy_count", "margin_rate"))
        self._register("get_fee_policy_summary", SummaryArgs, "Return seller-scoped aggregate marketplace fee-policy summary.", self._get_fee_policy_summary, domains=(BusinessDomainKey.PRICING, BusinessDomainKey.PROFIT_MARGIN), metrics=("products_missing_fee_policy_count",))
        self._register("get_pricing_policy_summary", SummaryArgs, "Return seller-scoped aggregate pricing-policy summary.", self._get_pricing_policy_summary, domains=(BusinessDomainKey.PRICING,), metrics=("products_missing_pricing_policy_count",))
        self._register("get_elasticity_summary", SummaryArgs, "Return seller-scoped aggregate demand elasticity evidence summary.", self._get_elasticity_summary, domains=(BusinessDomainKey.PRICING, BusinessDomainKey.SALES_REVENUE))
        self._register("get_seller_price_history_summary", SummaryArgs, "Return seller-side product price history summary; competitor price history is excluded.", self._get_seller_price_history_summary, domains=(BusinessDomainKey.PRICING,))
        self._register("get_promotion_summary", SummaryArgs, "Return seller-scoped promotion persistence and suitability summary.", self._get_promotion_summary, domains=(BusinessDomainKey.PROMOTION, BusinessDomainKey.DEAD_STOCK))
        self._register("get_promotion_outcome_summary", SummaryArgs, "Return seller-scoped promotion outcome and ROI summary.", self._get_promotion_outcome_summary, domains=(BusinessDomainKey.PROMOTION,))
        self._register("get_promotion_plans", PromotionRecordsArgs, "Return internal seller promotion plans; this never executes marketplace campaigns.", self._get_promotion_plans, domains=(BusinessDomainKey.PROMOTION,))
        self._register("get_promotion_results", PromotionRecordsArgs, "Return persisted seller promotion performance results.", self._get_promotion_results, domains=(BusinessDomainKey.PROMOTION,))
        self._register("compare_promotion_performance", PromotionRecordsArgs, "Aggregate persisted promotion performance and ROI where calculable.", self._compare_promotion_performance, domains=(BusinessDomainKey.PROMOTION,))
        self._register("get_product_price_changes", PriceHistoryArgs, "Return seller-side product/listing price changes from product_price_history.", self._get_product_price_changes, domains=(BusinessDomainKey.PRICING,))
        self._register("get_products_with_recent_price_changes", PriceHistoryArgs, "Return products with recent seller-side price changes.", self._get_products_with_recent_price_changes, domains=(BusinessDomainKey.PRICING,))
        self._register("get_dead_stock_summary", SummaryArgs, "Return seller-scoped aggregate dead-stock summary.", self._get_dead_stock_summary, domains=(BusinessDomainKey.DEAD_STOCK,), metrics=("dead_stock_count", "locked_capital"))
        self._register("get_visibility_summary", SummaryArgs, "Return seller-scoped aggregate SEO and visibility summary.", self._get_visibility_summary, domains=(BusinessDomainKey.SEO_VISIBILITY,))
        self._register("get_alert_recommendation_summary", SummaryArgs, "Return seller-scoped aggregate alert and recommendation summary.", self._get_alert_recommendation_summary, domains=(BusinessDomainKey.ALERTS, BusinessDomainKey.RECOMMENDATIONS), metrics=("pending_recommendation_count", "unresolved_alert_count"))
        self._register("get_alert_summary", SummaryArgs, "Return seller-scoped aggregate alert summary.", self._get_alert_summary, domains=(BusinessDomainKey.ALERTS,), metrics=("unresolved_alert_count",))
        self._register("get_recommendation_summary", SummaryArgs, "Return seller-scoped aggregate recommendation and action-center summary.", self._get_recommendation_summary, domains=(BusinessDomainKey.RECOMMENDATIONS,), metrics=("pending_recommendation_count",))
        self._register("count_products", CountProductsArgs, "Count seller-owned products with allowlisted setup and catalog filters.", self._count_products, domains=(BusinessDomainKey.PRODUCT_CATALOG,), metrics=("product_count", "active_product_count", "products_missing_cost_count", "products_missing_fee_policy_count", "products_with_stock_count", "products_with_no_sales_count"))
        self._register("list_products", ListProductsArgs, "List paginated seller-owned products with setup and catalog filters.", self._list_products, domains=(BusinessDomainKey.PRODUCT_CATALOG,))
        self._register("search_products", SearchProductsArgs, "Search seller-owned products by title, category, and searchable text.", self._search_products, domains=(BusinessDomainKey.PRODUCT_CATALOG,))
        self._register("get_product_profile", ProductProfileArgs, "Return a seller-owned product business profile with latest related signals.", self._get_product_profile, domains=(BusinessDomainKey.PRODUCT_CATALOG, BusinessDomainKey.INVENTORY, BusinessDomainKey.SALES_REVENUE, BusinessDomainKey.PROFIT_MARGIN, BusinessDomainKey.COMPETITOR, BusinessDomainKey.PRICING, BusinessDomainKey.DEAD_STOCK, BusinessDomainKey.SEO_VISIBILITY))
        self._register("get_products_missing_setup", ProductsMissingSetupArgs, "List seller-owned products missing required setup data and recommended next actions.", self._get_products_missing_setup, domains=(BusinessDomainKey.PRODUCT_CATALOG, BusinessDomainKey.PROFIT_MARGIN, BusinessDomainKey.INVENTORY, BusinessDomainKey.SALES_REVENUE, BusinessDomainKey.SEO_VISIBILITY), metrics=("products_missing_cost_count", "products_missing_fee_policy_count"))
        self._register("run_seller_metric_query", SellerMetricQueryArgs, "Execute one allowlisted catalog metric with backend-owned SQLAlchemy handlers only; raw SQL is never accepted.", self._run_seller_metric_query, domains=(BusinessDomainKey.PRODUCT_CATALOG, BusinessDomainKey.SALES_REVENUE, BusinessDomainKey.PROFIT_MARGIN, BusinessDomainKey.INVENTORY, BusinessDomainKey.COMPETITOR, BusinessDomainKey.DEAD_STOCK, BusinessDomainKey.RECOMMENDATIONS, BusinessDomainKey.ALERTS), metrics=("product_count", "active_product_count", "listed_product_count", "products_missing_cost_count", "products_missing_fee_policy_count", "products_missing_pricing_policy_count", "products_with_stock_count", "products_with_no_sales_count", "products_with_no_valid_imported_sales_count", "gross_revenue", "units_sold", "order_count", "average_order_value", "top_products_by_revenue", "revenue_trend", "previous_period_revenue", "revenue_change", "percentage_revenue_change", "products_with_revenue_decline", "average_selling_price_delta", "estimated_profit", "margin_rate", "products_excluded_from_profit", "current_inventory_value", "low_stock_product_count", "stockout_risk_count", "dead_stock_count", "locked_capital", "competitor_undercut_count", "competitor_price_gap", "pending_recommendation_count", "unresolved_alert_count"))
        self._register("get_revenue_summary", RevenueSummaryArgs, "Return deterministic seller revenue, units, AOV, previous-period comparison, top products, and completeness.", self._get_revenue_summary, domains=(BusinessDomainKey.SALES_REVENUE,), metrics=("gross_revenue", "net_revenue", "units_sold", "order_count", "average_order_value", "previous_period_revenue", "revenue_change", "percentage_revenue_change", "top_products_by_revenue", "products_with_revenue_decline"))
        self._register("get_sales_trends", SalesTrendsArgs, "Return deterministic seller sales trend time series by day, week, or month.", self._get_sales_trends, domains=(BusinessDomainKey.SALES_REVENUE,), metrics=("revenue_trend", "gross_revenue", "units_sold"))
        self._register("get_profit_summary", ProfitSummaryArgs, "Return deterministic estimated profit and margin summary with explicit product exclusions.", self._get_profit_summary, domains=(BusinessDomainKey.PROFIT_MARGIN, BusinessDomainKey.SALES_REVENUE), metrics=("estimated_profit", "margin_rate", "products_excluded_from_profit"))
        self._register("explain_revenue_change_deterministic", RevenueSummaryArgs, "Return deterministic revenue change factors; Groq must not calculate diagnosis.", self._explain_revenue_change_deterministic, domains=(BusinessDomainKey.SALES_REVENUE, BusinessDomainKey.INVENTORY, BusinessDomainKey.COMPETITOR, BusinessDomainKey.PRICING, BusinessDomainKey.PROMOTION), metrics=("gross_revenue", "units_sold", "average_order_value", "previous_period_revenue", "revenue_change", "percentage_revenue_change", "average_selling_price_delta", "revenue_trend"))
        self._register("get_top_products_by_revenue", TopProductsByRevenueArgs, "Return seller top products by deterministic revenue.", self._get_top_products_by_revenue, domains=(BusinessDomainKey.SALES_REVENUE, BusinessDomainKey.PRODUCT_CATALOG), metrics=("top_products_by_revenue", "gross_revenue", "units_sold", "order_count"))
        self._register("get_products_with_no_sales", ProductsWithNoSalesArgs, "Return products with no valid imported completed/fulfilled sales records, with completeness warning.", self._get_products_with_no_sales, domains=(BusinessDomainKey.SALES_REVENUE, BusinessDomainKey.PRODUCT_CATALOG), metrics=("products_with_no_sales_count",))
        self._register("get_today_actions", TodayActionsArgs, "Return prioritized read-only action candidates from existing recommendation feeds.", self._get_today_actions, domains=(BusinessDomainKey.RECOMMENDATIONS, BusinessDomainKey.INVENTORY, BusinessDomainKey.PRICING, BusinessDomainKey.DEAD_STOCK, BusinessDomainKey.ALERTS), metrics=("pending_recommendation_count", "unresolved_alert_count"))
        self._register("get_restock_recommendations", RestockRecommendationsArgs, "Return reorder recommendations from inventory engines.", self._get_restock_recommendations, domains=(BusinessDomainKey.INVENTORY, BusinessDomainKey.RECOMMENDATIONS), metrics=("low_stock_product_count", "stockout_risk_count"))
        self._register("get_inventory_risks", InventoryRisksArgs, "Return stockout and inventory risk assessments.", self._get_inventory_risks, domains=(BusinessDomainKey.INVENTORY,), metrics=("stockout_risk_count",))
        self._register("explain_revenue_drop", RevenueDropArgs, "Explain revenue movement using deterministic sales and business evidence.", self._explain_revenue_drop, domains=(BusinessDomainKey.SALES_REVENUE, BusinessDomainKey.INVENTORY, BusinessDomainKey.COMPETITOR, BusinessDomainKey.PRICING), metrics=("gross_revenue", "units_sold", "order_count", "average_order_value", "previous_period_revenue", "revenue_change", "percentage_revenue_change", "revenue_trend"))
        self._register("get_competitor_threats", CompetitorThreatsArgs, "Return competitor events and rankings that may threaten seller products.", self._get_competitor_threats, domains=(BusinessDomainKey.COMPETITOR,), metrics=("competitor_undercut_count", "competitor_price_gap"))
        self._register("get_pricing_recommendations", PricingRecommendationsArgs, "Return safe read-only dynamic pricing recommendations.", self._get_pricing_recommendations, domains=(BusinessDomainKey.PRICING, BusinessDomainKey.PROFIT_MARGIN, BusinessDomainKey.RECOMMENDATIONS), metrics=("estimated_profit", "margin_rate", "products_excluded_from_profit"))
        self._register("simulate_price_change", SimulatePriceChangeArgs, "Simulate candidate price or discount without changing marketplace price.", self._simulate_price_change, domains=(BusinessDomainKey.PRICING, BusinessDomainKey.PROFIT_MARGIN), metrics=("estimated_profit", "margin_rate"))
        self._register("get_promotion_recommendations", PromotionRecommendationsArgs, "Suggest read-only promotion candidates from pricing and dead-stock signals.", self._get_promotion_recommendations, domains=(BusinessDomainKey.PROMOTION, BusinessDomainKey.DEAD_STOCK, BusinessDomainKey.PRICING))
        self._register("get_dead_stock_recovery", DeadStockRecoveryArgs, "Return Phase 9 dead-stock recovery recommendations.", self._get_dead_stock_recovery, domains=(BusinessDomainKey.DEAD_STOCK, BusinessDomainKey.RECOMMENDATIONS), metrics=("dead_stock_count", "locked_capital"))
        self._register("get_seo_opportunities", SeoOpportunitiesArgs, "Return listing-quality and visibility opportunities.", self._get_seo_opportunities, domains=(BusinessDomainKey.SEO_VISIBILITY,))
        self._register("retrieve_business_memory", RetrieveBusinessMemoryArgs, "Retrieve seller-scoped Phase 12 RAG memory chunks.", self._retrieve_business_memory, max_runtime_ms=4000, domains=(BusinessDomainKey.RAG_MEMORY,))
        for spec in SOURCE_TOOL_SPECS.values():
            if spec.name not in self._tools:
                self._register(spec.name, SourceQueryArgs, spec.description, self._source_tool_handler(spec), domains=(spec.domain,))

    def _register(
        self,
        name: str,
        argument_schema: type[BaseModel],
        description: str,
        implementation: Callable[[CopilotToolContext, dict[str, Any]], dict[str, Any]],
        *,
        max_runtime_ms: int = DEFAULT_TOOL_RUNTIME_MS,
        domains: tuple[BusinessDomainKey, ...] = (),
        metrics: tuple[str, ...] = (),
    ) -> None:
        self._validate_catalog_references(domains=domains, metrics=metrics)
        self._tools[name] = ToolDefinition(
            name=name,
            version="v1",
            description=description,
            argument_schema=argument_schema,
            return_schema={"type": "object", "additionalProperties": True},
            safety_level=CopilotToolSafetyLevel.READ_ONLY,
            requires_confirmation=False,
            allowed_in_read_only_mode=True,
            max_runtime_ms=max_runtime_ms,
            implementation=implementation,
            seller_ownership_checks=("seller_id_from_context", "product_id_belongs_to_seller_when_present"),
            error_handling_behavior="Return structured error payloads; do not expose raw exceptions to the model.",
            catalog_domains=tuple(domain.value for domain in domains),
            catalog_metrics=metrics,
        )

    def _validate_catalog_references(self, *, domains: tuple[BusinessDomainKey, ...], metrics: tuple[str, ...]) -> None:
        for domain in domains:
            self._business_catalog.get_domain(domain)
        for metric in metrics:
            self._metric_catalog.get_metric(metric)

    def _get_business_overview(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_business_overview(
            seller_id=context.seller_id,
            from_date=args.get("from_date"),
            to_date=args.get("to_date"),
            marketplace=args.get("marketplace"),
            category=args.get("category"),
        )
        payload["missing_data"] = missing
        return payload

    def _get_product_setup_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_product_setup_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_inventory_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_inventory_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_sales_velocity_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_sales_velocity_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_stockout_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_stockout_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_reorder_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_reorder_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_inventory_aging_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_inventory_aging_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_competitor_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_competitor_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_competitor_price_change_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_competitor_price_change_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_competitor_undercut_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_competitor_undercut_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_market_opportunity_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_market_opportunity_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_scrape_health_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_scrape_health_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_pricing_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_pricing_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_fee_policy_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_fee_policy_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_pricing_policy_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_pricing_policy_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_elasticity_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_elasticity_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_seller_price_history_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_seller_price_history_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_promotion_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_promotion_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_promotion_outcome_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_promotion_outcome_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_promotion_plans(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_promotion_plans(seller_id=context.seller_id, product_id=args.get("product_id"), status=args.get("status"), marketplace=args.get("marketplace"), from_date=args.get("from_date"), to_date=args.get("to_date"), limit=args["limit"], offset=args["offset"])
        payload["missing_data"] = missing
        return payload

    def _get_promotion_results(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_promotion_results(seller_id=context.seller_id, product_id=args.get("product_id"), status=args.get("status"), marketplace=args.get("marketplace"), from_date=args.get("from_date"), to_date=args.get("to_date"), limit=args["limit"], offset=args["offset"])
        payload["missing_data"] = missing
        return payload

    def _compare_promotion_performance(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).compare_promotion_performance(seller_id=context.seller_id, product_id=args.get("product_id"), marketplace=args.get("marketplace"), from_date=args.get("from_date"), to_date=args.get("to_date"), limit=args["limit"], offset=args["offset"])
        payload["missing_data"] = missing
        return payload

    def _get_product_price_changes(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_price_history(seller_id=context.seller_id, product_id=args.get("product_id"), marketplace=args.get("marketplace"), from_date=args.get("from_date"), to_date=args.get("to_date"), limit=args["limit"], offset=args["offset"])
        payload["missing_data"] = missing
        return payload

    def _get_products_with_recent_price_changes(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_products_with_recent_price_changes(seller_id=context.seller_id, product_id=args.get("product_id"), marketplace=args.get("marketplace"), from_date=args.get("from_date"), to_date=args.get("to_date"), limit=args["limit"], offset=args["offset"])
        payload["missing_data"] = missing
        return payload

    def _get_dead_stock_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_dead_stock_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_visibility_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_visibility_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_alert_recommendation_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_alert_recommendation_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_alert_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_alert_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _get_recommendation_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_recommendation_summary(seller_id=context.seller_id, **args)
        payload["missing_data"] = missing
        return payload

    def _count_products(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).count_products(seller_id=context.seller_id, filters=_product_filters(args))
        payload["missing_data"] = missing
        return payload

    def _list_products(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).list_products(
            seller_id=context.seller_id,
            filters=_product_filters(args),
            sort_by=args.get("sort_by"),
            limit=args["limit"],
            offset=args["offset"],
        )
        payload["missing_data"] = missing
        return payload

    def _search_products(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).search_products(
            seller_id=context.seller_id,
            query=args["query"],
            category=args.get("category"),
            marketplace=args.get("marketplace"),
            limit=args["limit"],
        )
        payload["missing_data"] = missing
        return payload

    def _get_product_profile(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_product_profile(
            seller_id=context.seller_id,
            product_id=args["product_id"],
        )
        payload["missing_data"] = missing
        return payload

    def _get_products_missing_setup(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        setup_type = args.get("setup_type")
        payload, missing = self._data(context).get_products_missing_setup(
            seller_id=context.seller_id,
            setup_type=_enum_value(setup_type) if setup_type else None,
            category=args.get("category"),
            marketplace=args.get("marketplace"),
            limit=args["limit"],
            offset=args["offset"],
        )
        payload["missing_data"] = missing
        return payload

    def _run_seller_metric_query(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        data_access = self._data_access
        if data_access is not None and hasattr(data_access, "run_seller_metric_query"):
            payload, missing = data_access.run_seller_metric_query(seller_id=context.seller_id, **args)
            payload["missing_data"] = missing or payload.get("missing_data", [])
            return payload
        if context.db is None:
            raise RuntimeError("Metric execution requires a database session.")
        return MetricExecutionService(context.db, metric_catalog=self._metric_catalog).execute(
            seller_id=context.seller_id,
            metric_key=args["metric_key"],
            filters=args.get("filters") or {},
            group_by=args.get("group_by"),
            from_date=args.get("from_date"),
            to_date=args.get("to_date"),
            limit=args.get("limit"),
            offset=args.get("offset"),
        )

    def _get_revenue_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_revenue_summary(
            seller_id=context.seller_id,
            from_date=args["from_date"],
            to_date=args["to_date"],
            marketplace=args.get("marketplace"),
            product_id=args.get("product_id"),
            category=args.get("category"),
            compare_to_previous_period=args["compare_to_previous_period"],
        )
        payload["missing_data"] = missing
        return payload

    def _get_sales_trends(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_sales_trends(
            seller_id=context.seller_id,
            from_date=args["from_date"],
            to_date=args["to_date"],
            granularity=args["granularity"],
            marketplace=args.get("marketplace"),
            product_id=args.get("product_id"),
            category=args.get("category"),
        )
        payload["missing_data"] = missing
        return payload

    def _get_profit_summary(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_profit_summary(
            seller_id=context.seller_id,
            from_date=args["from_date"],
            to_date=args["to_date"],
            marketplace=args.get("marketplace"),
            product_id=args.get("product_id"),
            category=args.get("category"),
        )
        payload["missing_data"] = missing
        return payload

    def _explain_revenue_change_deterministic(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).explain_revenue_change_deterministic(
            seller_id=context.seller_id,
            from_date=args["from_date"],
            to_date=args["to_date"],
            compare_to_previous_period=args["compare_to_previous_period"],
            marketplace=args.get("marketplace"),
            product_id=args.get("product_id"),
            category=args.get("category"),
        )
        payload["missing_data"] = missing
        return payload

    def _get_top_products_by_revenue(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_top_products_by_revenue(
            seller_id=context.seller_id,
            from_date=args["from_date"],
            to_date=args["to_date"],
            limit=args["limit"],
            category=args.get("category"),
            marketplace=args.get("marketplace"),
        )
        payload["missing_data"] = missing
        return payload

    def _get_products_with_no_sales(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).get_products_with_no_sales(
            seller_id=context.seller_id,
            since_date=args.get("since_date"),
            category=args.get("category"),
            marketplace=args.get("marketplace"),
            limit=args["limit"],
            offset=args["offset"],
        )
        payload["missing_data"] = missing
        return payload

    def _get_today_actions(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        rows, missing = self._data(context).get_today_actions(seller_id=context.seller_id, product_id=args.get("product_id"), limit=args["limit"])
        return {"actions": rows, "missing_data": missing}

    def _get_restock_recommendations(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        rows, missing = self._data(context).get_restock_recommendations(seller_id=context.seller_id, product_id=args.get("product_id"), category=args.get("category"), limit=args["limit"])
        return {"recommendations": rows, "missing_data": missing}

    def _get_inventory_risks(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        rows, missing = self._data(context).get_inventory_risks(seller_id=context.seller_id, product_id=args.get("product_id"), risk_level=args.get("risk_level"), limit=args["limit"])
        return {"risks": rows, "missing_data": missing}

    def _explain_revenue_drop(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).explain_revenue_drop(seller_id=context.seller_id, product_id=args.get("product_id"), from_date=args["from_date"], to_date=args["to_date"], compare_to_previous_period=args["compare_to_previous_period"])
        payload["missing_data"] = missing
        return payload

    def _get_competitor_threats(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        rows, missing = self._data(context).get_competitor_threats(seller_id=context.seller_id, product_id=args.get("product_id"), from_date=args.get("from_date"), to_date=args.get("to_date"), limit=args["limit"])
        return {"threats": rows, "missing_data": missing}

    def _get_pricing_recommendations(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        rows, missing = self._data(context).get_pricing_recommendations(seller_id=context.seller_id, product_id=args.get("product_id"), limit=args["limit"])
        return {"recommendations": rows, "missing_data": missing}

    def _simulate_price_change(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).simulate_price_change(seller_id=context.seller_id, product_id=args["product_id"], candidate_price=args.get("candidate_price"), candidate_discount_rate=args.get("candidate_discount_rate"), forecast_horizon_days=args["forecast_horizon_days"])
        payload["missing_data"] = missing
        return payload

    def _get_promotion_recommendations(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        rows, missing = self._data(context).get_promotion_recommendations(seller_id=context.seller_id, product_id=args.get("product_id"), category=args.get("category"), limit=args["limit"])
        return {"promotions": rows, "missing_data": missing}

    def _get_dead_stock_recovery(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        rows, missing = self._data(context).get_dead_stock_recovery(seller_id=context.seller_id, product_id=args.get("product_id"), limit=args["limit"])
        return {"recovery": rows, "missing_data": missing}

    def _get_seo_opportunities(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        rows, missing = self._data(context).get_seo_opportunities(seller_id=context.seller_id, product_id=args.get("product_id"), limit=args["limit"])
        return {"opportunities": rows, "missing_data": missing}

    def _retrieve_business_memory(self, context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
        payload, missing = self._data(context).retrieve_business_memory(seller_id=context.seller_id, question=args["question"], product_id=args.get("product_id"), source_types=args.get("source_types"), from_date=args.get("from_date"), to_date=args.get("to_date"), top_k=args["top_k"])
        payload["missing_data"] = missing
        return payload

    def _source_tool_handler(self, spec: SourceToolSpec) -> Callable[[CopilotToolContext, dict[str, Any]], dict[str, Any]]:
        def handler(context: CopilotToolContext, args: dict[str, Any]) -> dict[str, Any]:
            payload, missing = self._data(context).get_business_source(
                seller_id=context.seller_id,
                spec=spec,
                filters=args,
                limit=args["limit"],
                offset=args["offset"],
            )
            payload["missing_data"] = missing
            return payload

        return handler

    def _error_result(
        self,
        *,
        name: str,
        version: str,
        status: ToolExecutionStatus,
        code: str,
        message: str,
        start_ms: float,
        context: CopilotToolContext | None = None,
        tool: ToolDefinition | None = None,
    ) -> ToolExecutionResult:
        runtime_ms = elapsed_ms(start_ms)
        if context and tool:
            self._log(context=context, tool=tool, status=status, runtime_ms=runtime_ms, error_code=code)
        return ToolExecutionResult(
            tool_name=name,
            tool_version=version,
            status=status,
            data={"missing_data": [message]},
            evidence=[],
            missing_data=[message],
            error={"code": code, "message": message},
            runtime_ms=runtime_ms,
        )

    def _log(self, *, context: CopilotToolContext, tool: ToolDefinition, status: ToolExecutionStatus, runtime_ms: int, evidence_count: int | None = None, error_code: str | None = None) -> None:
        log_event(
            logger,
            logging.INFO,
            "copilot_tool_call",
            seller_id=context.seller_id,
            user_id=context.user_id,
            request_id=context.request_id,
            tool_name=tool.name,
            tool_version=tool.version,
            safety_level=tool.safety_level.value,
            status=status.value,
            runtime_ms=runtime_ms,
            evidence_count=evidence_count,
            error_code=error_code,
        )


class SqlAlchemyCopilotToolDataAccess:
    def __init__(self, db: Session) -> None:
        self._db = db

    def verify_product_owned(self, *, seller_id: UUID, product_id: UUID) -> bool:
        return self._db.execute(select(Product.id).where(Product.id == product_id, Product.seller_id == seller_id)).scalar_one_or_none() is not None

    def get_business_overview(self, *, seller_id: UUID, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None) -> tuple[dict[str, Any], list[str]]:
        args = {"seller_id": seller_id, "product_id": None, "from_date": from_date, "to_date": to_date, "marketplace": marketplace, "category": category, "limit": 5, "offset": 0}
        product_setup, setup_missing = self.get_product_setup_summary(**args)
        revenue, revenue_missing = self.get_revenue_summary(seller_id=seller_id, from_date=from_date or date(1970, 1, 1), to_date=to_date or date.today(), marketplace=marketplace, product_id=None, category=category, compare_to_previous_period=False)
        profit, profit_missing = self.get_profit_summary(seller_id=seller_id, from_date=from_date or date(1970, 1, 1), to_date=to_date or date.today(), marketplace=marketplace, product_id=None, category=category)
        inventory, inventory_missing = self.get_inventory_summary(**args)
        competitor, competitor_missing = self.get_competitor_summary(**args)
        pricing, pricing_missing = self.get_pricing_summary(**args)
        dead_stock, dead_missing = self.get_dead_stock_summary(**args)
        alerts, alert_missing = self.get_alert_recommendation_summary(**args)
        memory = self._memory_coverage_summary(seller_id=seller_id)
        missing = sorted(set(setup_missing + revenue_missing + profit_missing + inventory_missing + competitor_missing + pricing_missing + dead_missing + alert_missing + memory["missing_data"]))
        top_issues = _top_issues(product_setup, inventory, pricing, dead_stock, alerts, missing)
        next_actions = _next_actions_from_issues(top_issues)
        evidence = _dedupe_evidence(
            product_setup["evidence"]
            + revenue.get("evidence", [])
            + profit.get("evidence", [])
            + inventory["evidence"]
            + competitor["evidence"]
            + pricing["evidence"]
            + dead_stock["evidence"]
            + alerts["evidence"]
            + [_evidence("rag_memory_documents", "seller_scope")]
        )
        return {
            "overview": {
                "product_counts": product_setup["summary"],
                "listing_counts": product_setup["listing_counts"],
                "missing_setup_counts": product_setup["missing_setup_counts"],
                "revenue_summary": revenue,
                "profit_summary": profit,
                "inventory_risk_summary": inventory["summary"],
                "competitor_threat_summary": competitor["summary"],
                "dead_stock_summary": dead_stock["summary"],
                "alert_recommendation_summary": alerts["summary"],
                "memory_coverage_summary": memory["summary"],
            },
            "top_issues": top_issues[:5],
            "recommended_next_actions": next_actions[:5],
            "filters_used": _clean_filter_payload({"from_date": from_date, "to_date": to_date, "category": category, "marketplace": marketplace}),
            "confidence": "LOW" if missing else "HIGH",
            "freshness": self._freshness_summary(seller_id=seller_id),
            "evidence": evidence,
            "missing_data_summary": missing,
        }, missing

    def get_product_setup_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del product_id, from_date, to_date, limit, offset
        filters = {"category": category, "marketplace": marketplace}
        total = self._product_count(seller_id=seller_id, filters=filters)
        active = self._product_count(seller_id=seller_id, filters={**filters, "status": "ACTIVE"})
        listed = self._count_rows(select(func.count()).select_from(ProductMarketplaceListing).join(Product, Product.id == ProductMarketplaceListing.product_id).where(ProductMarketplaceListing.seller_id == seller_id, Product.seller_id == seller_id, ProductMarketplaceListing.archived_at.is_(None), ProductMarketplaceListing.listing_status == ProductMarketplaceListingStatus.ACTIVE))
        missing_cost = self._product_count(seller_id=seller_id, filters={**filters, "missing_cost": True})
        missing_fee = self._product_count(seller_id=seller_id, filters={**filters, "missing_fee_policy": True})
        missing_pricing = self._product_count(seller_id=seller_id, filters={**filters, "missing_pricing_policy": True})
        missing = self._unsupported_filter_notes(filters, seller_id=seller_id)
        return self._summary_payload(
            summary={"total_products": total, "active_product_count": active},
            evidence_tables=("products", "product_marketplace_listings", "marketplace_fee_policies", "pricing_policies"),
            freshness=self._freshness_for_tables(seller_id, ("products", "product_marketplace_listings", "marketplace_fee_policies", "pricing_policies")),
            extra={"listing_counts": {"active_listed_products": listed}, "missing_setup_counts": {"missing_cost": missing_cost, "missing_fee_policy": missing_fee, "missing_pricing_policy": missing_pricing}},
        ), missing

    def get_inventory_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del from_date, to_date, offset
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=marketplace)
        if product_ids:
            aggregate_row = self._db.execute(
                select(
                    func.sum(case((Product.stock_quantity > 0, 1), else_=0)),
                    func.coalesce(func.sum(Product.stock_quantity), 0),
                    func.sum(case((Product.stock_quantity <= 5, 1), else_=0)),
                    func.sum(case((Product.cost_price.is_(None), 1), else_=0)),
                    func.coalesce(func.sum(case((Product.cost_price.is_not(None), Product.stock_quantity * Product.cost_price), else_=0)), 0),
                ).where(Product.seller_id == seller_id, Product.id.in_(product_ids))
            ).one()
        else:
            aggregate_row = (0, 0, 0, 0, Decimal("0"))
        total_with_stock, total_units, low_stock_count, missing_cost, inventory_value = aggregate_row
        if missing_cost:
            missing.append("MISSING_PRODUCT_COST")
        top_affected_products = (
            self._db.execute(
                select(Product)
                .where(Product.seller_id == seller_id, Product.id.in_(product_ids), Product.stock_quantity <= 5)
                .order_by(Product.stock_quantity.asc(), Product.updated_at.desc())
                .limit(max(1, limit))
            )
            .scalars()
            .all()
            if product_ids
            else []
        )
        stockout_count = 0
        reorder_count = 0
        dead_count = 0
        if self._table_exists("inventory_risk_assessments"):
            stockout_count = self._count_rows(select(func.count()).select_from(InventoryRiskAssessment).where(InventoryRiskAssessment.seller_id == seller_id, InventoryRiskAssessment.risk_level.in_([InventoryRiskLevel.HIGH, InventoryRiskLevel.CRITICAL])))
        if self._table_exists("reorder_recommendations"):
            reorder_count = self._count_rows(select(func.count()).select_from(ReorderRecommendation).where(ReorderRecommendation.seller_id == seller_id, ReorderRecommendation.recommendation_status == ReorderRecommendationStatus.OPEN))
        if self._table_exists("dead_stock_assessments"):
            dead_count = self._count_rows(select(func.count()).select_from(DeadStockAssessment).where(DeadStockAssessment.seller_id == seller_id, DeadStockAssessment.classification.in_(["AT_RISK", "DEAD_STOCK"])))
        summary = {
            "total_products_with_stock": int(total_with_stock or 0),
            "total_available_units": int(total_units or 0),
            "low_stock_count": int(low_stock_count or 0),
            "stockout_risk_count": stockout_count,
            "reorder_recommendation_count": reorder_count,
            "overstock_or_dead_stock_count": dead_count,
            "inventory_value": inventory_value if not missing_cost else None,
            "missing_inventory_data": sorted(set(missing)),
        }
        return self._summary_payload(
            summary=summary,
            evidence_tables=("products", "inventory_risk_assessments", "reorder_recommendations", "dead_stock_assessments"),
            freshness=self._freshness_for_tables(seller_id, ("products", "inventory_risk_assessments", "reorder_recommendations", "dead_stock_assessments")),
            extra={"top_affected_products": [_product_ref(product) | {"stock_quantity": product.stock_quantity} for product in top_affected_products]},
        ), missing

    def get_sales_velocity_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del offset
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=marketplace)
        stmt = select(SalesVelocity).options(joinedload(SalesVelocity.product)).where(SalesVelocity.seller_id == seller_id)
        stmt = self._filter_by_product_ids(stmt, SalesVelocity.product_id, product_ids)
        stmt = _date_filter(stmt, SalesVelocity.calculated_at, from_date, to_date)
        rows = self._db.execute(stmt.order_by(SalesVelocity.daily_sales_rate.desc(), SalesVelocity.calculated_at.desc()).limit(max(limit, 1))).scalars().all()
        all_rows = self._db.execute(stmt).scalars().all()
        summary = {
            "products_with_velocity": len({row.product_id for row in all_rows}),
            "high_velocity_count": sum(1 for row in all_rows if Decimal(row.daily_sales_rate or 0) >= Decimal("5")),
            "low_velocity_count": sum(1 for row in all_rows if Decimal(row.daily_sales_rate or 0) > 0 and Decimal(row.daily_sales_rate or 0) < Decimal("1")),
            "zero_velocity_count": sum(1 for row in all_rows if Decimal(row.daily_sales_rate or 0) == 0),
            "insufficient_velocity_data_count": sum(1 for row in all_rows if _enum_value(row.data_status) == "INSUFFICIENT"),
        }
        if not all_rows:
            missing.append("NO_SALES_VELOCITY_DATA")
        return self._summary_payload(
            summary=summary,
            evidence_tables=("sales_velocity", "products"),
            freshness=self._freshness_for_tables(seller_id, ("sales_velocity", "products")),
            extra={"top_products": [_sales_velocity_payload(row) | {"product": _product_ref(row.product)} for row in rows[:limit]]},
        ), sorted(set(missing))

    def get_stockout_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del offset
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=marketplace)
        stmt = select(StockoutPrediction).options(joinedload(StockoutPrediction.product)).where(StockoutPrediction.seller_id == seller_id)
        stmt = self._filter_by_product_ids(stmt, StockoutPrediction.product_id, product_ids)
        stmt = _date_filter(stmt, StockoutPrediction.calculated_at, from_date, to_date)
        rows = self._db.execute(stmt).scalars().all()
        top = sorted(rows, key=lambda row: (Decimal(row.days_remaining or 0), row.calculated_at), reverse=False)[:limit]
        status_counts = _counts_by(rows, "prediction_status")
        summary = {
            "predicted_stockout_count": status_counts.get("PREDICTED", 0),
            "already_out_of_stock_count": status_counts.get("ALREADY_OUT_OF_STOCK", 0),
            "no_recent_demand_count": status_counts.get("NO_RECENT_DEMAND", 0),
            "insufficient_data_count": status_counts.get("INSUFFICIENT_DATA", 0),
            "products_with_stockout_predictions": len({row.product_id for row in rows}),
        }
        if not rows:
            missing.append("NO_STOCKOUT_PREDICTION_DATA")
        return self._summary_payload(
            summary=summary,
            evidence_tables=("stockout_predictions", "products"),
            freshness=self._freshness_for_tables(seller_id, ("stockout_predictions", "products")),
            extra={"top_affected_products": [_stockout_payload(row) | {"product": _product_ref(row.product), "inventory_position": row.inventory_position} for row in top]},
        ), sorted(set(missing))

    def get_reorder_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del offset
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=marketplace)
        stmt = select(ReorderRecommendation).options(joinedload(ReorderRecommendation.product)).where(ReorderRecommendation.seller_id == seller_id)
        stmt = self._filter_by_product_ids(stmt, ReorderRecommendation.product_id, product_ids)
        stmt = _date_filter(stmt, ReorderRecommendation.generated_at, from_date, to_date)
        rows = self._db.execute(stmt).scalars().all()
        status_counts = _counts_by(rows, "recommendation_status")
        action_counts = _counts_by(rows, "action")
        open_rows = [row for row in rows if row.recommendation_status == ReorderRecommendationStatus.OPEN]
        top = sorted(open_rows, key=lambda row: (row.reorder_deadline or date.max, -float(row.confidence_score or 0)))[:limit]
        summary = {
            "open_reorder_count": status_counts.get("OPEN", 0),
            "reorder_action_count": action_counts.get("REORDER", 0),
            "hold_action_count": action_counts.get("HOLD", 0),
            "overdue_reorder_count": sum(1 for row in open_rows if row.reorder_deadline and row.reorder_deadline <= date.today()),
            "total_recommended_quantity": sum(int(row.recommended_quantity or 0) for row in open_rows),
            "recommendations_by_status": status_counts,
        }
        if not rows:
            missing.append("NO_REORDER_RECOMMENDATION_DATA")
        return self._summary_payload(
            summary=summary,
            evidence_tables=("reorder_recommendations", "products"),
            freshness=self._freshness_for_tables(seller_id, ("reorder_recommendations", "products")),
            extra={"top_affected_products": [{"product": _product_ref(row.product), "recommended_quantity": row.recommended_quantity, "deadline": row.reorder_deadline, "priority": _risk_from_reorder(row), "evidence": _evidence("reorder_recommendations", row.id, row.evidence)} for row in top]},
        ), sorted(set(missing))

    def get_inventory_aging_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del offset
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=marketplace)
        stmt = select(InventoryAgingSnapshot).options(joinedload(InventoryAgingSnapshot.product)).where(InventoryAgingSnapshot.seller_id == seller_id)
        stmt = self._filter_by_product_ids(stmt, InventoryAgingSnapshot.product_id, product_ids)
        stmt = _date_filter(stmt, InventoryAgingSnapshot.calculated_at, from_date, to_date)
        rows = self._db.execute(stmt).scalars().all()
        top = sorted(rows, key=lambda row: (row.oldest_age_days or -1, row.calculated_at), reverse=True)[:limit]
        summary = {
            "products_with_aging_data": len({row.product_id for row in rows}),
            "aged_inventory_count": sum(1 for row in rows if (row.oldest_age_days or 0) > 60),
            "estimated_age_count": sum(1 for row in rows if row.is_estimated),
            "unavailable_age_count": sum(1 for row in rows if _enum_value(row.age_source) == "UNAVAILABLE"),
            "total_eligible_unsold_quantity": sum(int(row.eligible_unsold_quantity or 0) for row in rows),
        }
        if not rows:
            missing.append("NO_INVENTORY_AGING_DATA")
        return self._summary_payload(
            summary=summary,
            evidence_tables=("inventory_aging_snapshots", "products"),
            freshness=self._freshness_for_tables(seller_id, ("inventory_aging_snapshots", "products")),
            extra={"top_affected_products": [_inventory_age_payload(row) | {"product": _product_ref(row.product), "eligible_unsold_quantity": row.eligible_unsold_quantity} for row in top]},
        ), sorted(set(missing))

    def get_competitor_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del marketplace, category, limit, offset
        event_stmt = select(CompetitorEvent).where(CompetitorEvent.seller_id == seller_id)
        if product_id:
            event_stmt = event_stmt.where(CompetitorEvent.product_id == product_id)
        event_stmt = _date_filter(event_stmt, CompetitorEvent.detected_at, from_date, to_date)
        recent_drops = self._count_rows(select(func.count()).select_from(event_stmt.where(CompetitorEvent.event_type == "PRICE_DROP").subquery()))
        oos = self._count_rows(select(func.count()).select_from(event_stmt.where(CompetitorEvent.event_type == "OUT_OF_STOCK").subquery()))
        latest_scrape = self._db.execute(select(ScrapeRun).where(ScrapeRun.seller_id == seller_id).order_by(ScrapeRun.created_at.desc()).limit(1)).scalar_one_or_none()
        summary = {
            "tracked_competitor_count": self._count_rows(select(func.count(func.distinct(Competitor.id))).select_from(Competitor).join(Product, Product.id == Competitor.product_id).where(Product.seller_id == seller_id)),
            "products_with_competitor_data": self._count_rows(select(func.count(func.distinct(CompetitorSnapshot.product_id))).select_from(CompetitorSnapshot).join(Product, Product.id == CompetitorSnapshot.product_id).where(Product.seller_id == seller_id)),
            "recent_competitor_price_drops": recent_drops,
            "undercut_products_count": MetricExecutionService(self._db).execute(seller_id=seller_id, metric_key="competitor_undercut_count", filters={}, from_date=from_date, to_date=to_date)["value"],
            "out_of_stock_competitor_opportunities": oos,
            "market_opportunities_count": self._count_rows(select(func.count()).select_from(MarketOpportunity).where(MarketOpportunity.seller_id == seller_id, MarketOpportunity.status == MarketOpportunityStatus.OPEN)),
            "latest_scrape_status": getattr(latest_scrape, "status", None),
        }
        missing = [] if summary["tracked_competitor_count"] else ["NO_COMPETITOR_DATA"]
        return self._summary_payload(summary=summary, evidence_tables=("competitors", "competitor_snapshots", "competitor_events", "market_opportunities", "scrape_runs"), freshness=self._freshness_for_tables(seller_id, ("competitor_snapshots", "competitor_events", "market_opportunities", "scrape_runs"))), missing

    def get_competitor_price_change_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del offset
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=marketplace)
        stmt = select(CompetitorEvent).options(joinedload(CompetitorEvent.product), joinedload(CompetitorEvent.competitor)).where(CompetitorEvent.seller_id == seller_id, CompetitorEvent.event_type.in_(("PRICE_DROP", "PRICE_RISE")))
        stmt = self._filter_by_product_ids(stmt, CompetitorEvent.product_id, product_ids)
        stmt = _date_filter(stmt, CompetitorEvent.detected_at, from_date, to_date)
        rows = self._db.execute(stmt.order_by(CompetitorEvent.detected_at.desc(), CompetitorEvent.severity.desc()).limit(limit)).scalars().all()
        all_rows = self._db.execute(stmt).scalars().all()
        summary = {
            "price_drop_count": sum(1 for row in all_rows if _enum_value(row.event_type) == "PRICE_DROP"),
            "price_rise_count": sum(1 for row in all_rows if _enum_value(row.event_type) == "PRICE_RISE"),
            "products_with_price_change_events": len({row.product_id for row in all_rows}),
        }
        if not all_rows:
            missing.append("NO_COMPETITOR_PRICE_CHANGE_EVENTS")
        return self._summary_payload(
            summary=summary,
            evidence_tables=("competitor_events", "competitors", "products"),
            freshness=self._freshness_for_tables(seller_id, ("competitor_events", "competitors", "products")),
            extra={"latest_price_change_events": [_competitor_event_payload(row) for row in rows]},
        ), sorted(set(missing))

    def get_competitor_undercut_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del offset
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=marketplace)
        stmt = select(CompetitorSnapshot).options(joinedload(CompetitorSnapshot.product), joinedload(CompetitorSnapshot.competitor)).join(Product, Product.id == CompetitorSnapshot.product_id).where(Product.seller_id == seller_id, Product.selling_price.is_not(None), CompetitorSnapshot.price.is_not(None), CompetitorSnapshot.price < Product.selling_price)
        stmt = self._filter_by_product_ids(stmt, CompetitorSnapshot.product_id, product_ids)
        stmt = _date_filter(stmt, CompetitorSnapshot.captured_at, from_date, to_date)
        rows = self._db.execute(stmt.order_by(CompetitorSnapshot.captured_at.desc()).limit(limit)).scalars().all()
        all_rows = self._db.execute(stmt).scalars().all()
        summary = {
            "undercut_snapshot_count": len(all_rows),
            "undercut_product_count": len({row.product_id for row in all_rows}),
            "tracked_competitors_undercutting": len({row.competitor_id for row in all_rows}),
        }
        if not all_rows:
            missing.append("NO_COMPETITOR_UNDERCUT_DATA")
        return self._summary_payload(
            summary=summary,
            evidence_tables=("competitor_snapshots", "products"),
            freshness=self._freshness_for_tables(seller_id, ("competitor_snapshots", "products")),
            extra={"top_affected_products": [{"product": _product_ref(row.product), "competitor": _competitor_ref(row.competitor), "competitor_price": row.price, "seller_price": row.product.selling_price, "price_gap": Decimal(str(row.product.selling_price)) - Decimal(str(row.price)), "evidence": _evidence("competitor_snapshots", row.id)} for row in rows]},
        ), sorted(set(missing))

    def get_market_opportunity_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del marketplace, offset
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=None)
        stmt = select(MarketOpportunity).options(joinedload(MarketOpportunity.product), joinedload(MarketOpportunity.competitor)).where(MarketOpportunity.seller_id == seller_id)
        stmt = self._filter_by_product_ids(stmt, MarketOpportunity.product_id, product_ids)
        stmt = _date_filter(stmt, MarketOpportunity.detected_at, from_date, to_date)
        rows = self._db.execute(stmt).scalars().all()
        open_rows = [row for row in rows if row.status == MarketOpportunityStatus.OPEN]
        top = sorted(open_rows, key=lambda row: (row.opportunity_score, row.detected_at), reverse=True)[:limit]
        summary = {
            "open_opportunity_count": len(open_rows),
            "opportunities_by_level": _counts_by(rows, "opportunity_level"),
            "competitor_stock_opportunities": sum(1 for row in rows if _enum_value(row.opportunity_type) == "COMPETITOR_OUT_OF_STOCK"),
            "estimated_revenue_total": _sum_decimal(row.estimated_revenue for row in open_rows),
        }
        if not rows:
            missing.append("NO_MARKET_OPPORTUNITY_DATA")
        return self._summary_payload(
            summary=summary,
            evidence_tables=("market_opportunities", "competitor_events", "products"),
            freshness=self._freshness_for_tables(seller_id, ("market_opportunities", "competitor_events", "products")),
            extra={"top_opportunities": [_market_opportunity_payload(row) for row in top]},
        ), sorted(set(missing))

    def get_scrape_health_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del category, limit, offset
        stmt = select(ScrapeRun).where(ScrapeRun.seller_id == seller_id)
        if product_id:
            stmt = stmt.where(ScrapeRun.product_id == product_id)
        if marketplace:
            stmt = stmt.where(ScrapeRun.marketplace == marketplace)
        stmt = _date_filter(stmt, ScrapeRun.created_at, from_date, to_date)
        rows = self._db.execute(stmt).scalars().all()
        completed = [row for row in rows if row.status == "COMPLETED"]
        latest_completed = max((row.completed_at or row.finished_at or row.created_at for row in completed), default=None)
        stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        summary = {
            "total_scrape_runs": len(rows),
            "completed_scrape_count": len(completed),
            "failed_scrape_count": sum(1 for row in rows if row.status == "FAILED"),
            "partial_scrape_count": sum(1 for row in rows if row.status == "PARTIAL"),
            "stale_scrape_count": sum(1 for row in completed if (row.completed_at or row.finished_at or row.created_at) < stale_cutoff),
            "latest_completed_scrape_time": _scalar_iso(latest_completed),
        }
        missing = [] if rows else ["NO_SCRAPE_RUN_DATA"]
        return self._summary_payload(summary=summary, evidence_tables=("scrape_runs",), freshness=self._freshness_for_tables(seller_id, ("scrape_runs",))), missing

    def get_pricing_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del from_date, to_date, limit, offset
        filters = {"category": category, "marketplace": marketplace}
        if product_id:
            filters["product_id"] = product_id
        products = self._db.execute(self._product_statement(seller_id=seller_id, filters=filters)).scalars().all()
        pricing_recs = self._count_rows(select(func.count()).select_from(DynamicPricingRecommendation).where(DynamicPricingRecommendation.seller_id == seller_id, DynamicPricingRecommendation.recommendation_status == DynamicPricingRecommendationStatus.OPEN))
        missing_fee = self._product_count(seller_id=seller_id, filters={**filters, "missing_fee_policy": True})
        missing_pricing = self._product_count(seller_id=seller_id, filters={**filters, "missing_pricing_policy": True})
        unsafe = self._count_rows(select(func.count()).select_from(DynamicPricingRecommendation).where(DynamicPricingRecommendation.seller_id == seller_id, DynamicPricingRecommendation.minimum_safe_price.is_not(None), DynamicPricingRecommendation.recommended_price < DynamicPricingRecommendation.minimum_safe_price))
        margin_risk = sum(1 for product in products if product.selling_price is not None and product.cost_price is not None and product.selling_price <= product.cost_price)
        summary = {
            "products_with_pricing_recommendations": pricing_recs,
            "products_missing_fee_policy": missing_fee,
            "products_missing_pricing_policy": missing_pricing,
            "products_unsafe_to_discount": unsafe,
            "products_with_margin_risk": margin_risk,
            "recent_seller_price_changes": self._count_rows(select(func.count()).select_from(ProductPriceHistory).where(ProductPriceHistory.seller_id == seller_id)),
            "latest_pricing_analytics_freshness": _scalar_iso(self._db.execute(select(func.max(PricingAnalyticsSnapshot.calculated_at)).where(PricingAnalyticsSnapshot.seller_id == seller_id)).scalar_one_or_none()),
            "latest_seller_price_change_at": _scalar_iso(self._db.execute(select(func.max(ProductPriceHistory.changed_at)).where(ProductPriceHistory.seller_id == seller_id)).scalar_one_or_none()),
        }
        missing = self._unsupported_filter_notes(filters, seller_id=seller_id, product_ids=[p.id for p in products])
        return self._summary_payload(summary=summary, evidence_tables=("dynamic_pricing_recommendations", "marketplace_fee_policies", "pricing_policies", "pricing_analytics_snapshots", "product_price_history"), freshness=self._freshness_for_tables(seller_id, ("dynamic_pricing_recommendations", "marketplace_fee_policies", "pricing_policies", "pricing_analytics_snapshots", "product_price_history"))), missing

    def get_fee_policy_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del from_date, to_date, limit, offset
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=marketplace)
        fee_ids = self._product_ids_with_fee_policy(seller_id=seller_id, product_ids=product_ids)
        stmt = select(MarketplaceFeePolicy).where(MarketplaceFeePolicy.seller_id == seller_id)
        if marketplace:
            stmt = stmt.where(MarketplaceFeePolicy.marketplace == marketplace)
        if category:
            stmt = stmt.where((MarketplaceFeePolicy.category == category) | (MarketplaceFeePolicy.category.is_(None)))
        policies = self._db.execute(stmt).scalars().all()
        summary = {
            "active_fee_policy_count": sum(1 for row in policies if row.is_active),
            "inactive_fee_policy_count": sum(1 for row in policies if not row.is_active),
            "products_missing_fee_policy": max(0, len(product_ids) - len(fee_ids)),
            "products_with_fee_policy": len(fee_ids),
            "policy_scope_counts": _policy_scope_counts(policies),
        }
        if not policies:
            missing.append("NO_MARKETPLACE_FEE_POLICIES")
        return self._summary_payload(summary=summary, evidence_tables=("marketplace_fee_policies", "products"), freshness=self._freshness_for_tables(seller_id, ("marketplace_fee_policies", "products"))), sorted(set(missing))

    def get_pricing_policy_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del from_date, to_date, marketplace, limit, offset
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=None)
        pricing_ids = self._product_ids_with_pricing_policy(seller_id=seller_id, product_ids=product_ids)
        stmt = select(PricingPolicy).where(PricingPolicy.seller_id == seller_id)
        if product_id:
            stmt = stmt.where(PricingPolicy.product_id == product_id)
        policies = self._db.execute(stmt).scalars().all()
        active = [row for row in policies if row.is_active]
        summary = {
            "active_pricing_policy_count": len(active),
            "inactive_pricing_policy_count": len(policies) - len(active),
            "products_missing_pricing_policy": max(0, len(product_ids) - len(pricing_ids)),
            "products_with_pricing_policy": len(pricing_ids),
            "objectives": _counts_by(policies, "objective"),
        }
        if not policies:
            missing.append("NO_PRICING_POLICIES")
        return self._summary_payload(summary=summary, evidence_tables=("pricing_policies", "products"), freshness=self._freshness_for_tables(seller_id, ("pricing_policies", "products"))), sorted(set(missing))

    def get_elasticity_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del offset
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=marketplace)
        stmt = select(DemandElasticityEstimate).options(joinedload(DemandElasticityEstimate.product)).where(DemandElasticityEstimate.seller_id == seller_id)
        stmt = self._filter_by_product_ids(stmt, DemandElasticityEstimate.product_id, product_ids)
        stmt = _date_filter(stmt, DemandElasticityEstimate.calculated_at, from_date, to_date)
        rows = self._db.execute(stmt.order_by(DemandElasticityEstimate.calculated_at.desc()).limit(max(limit, 1))).scalars().all()
        all_rows = self._db.execute(stmt).scalars().all()
        products_with_estimates = {row.product_id for row in all_rows}
        summary = {
            "products_with_elasticity_evidence": len(products_with_estimates),
            "products_lacking_elasticity_evidence": max(0, len(product_ids) - len(products_with_estimates)),
            "estimation_methods": _counts_by(all_rows, "estimation_method"),
            "insufficient_elasticity_count": sum(1 for row in all_rows if _enum_value(row.data_status) == "INSUFFICIENT"),
        }
        if not all_rows:
            missing.append("NO_ELASTICITY_EVIDENCE")
        return self._summary_payload(
            summary=summary,
            evidence_tables=("demand_elasticity_estimates", "products"),
            freshness=self._freshness_for_tables(seller_id, ("demand_elasticity_estimates", "products")),
            extra={"top_pricing_risks": [{"product": _product_ref(row.product), "method": _enum_value(row.estimation_method), "data_status": _enum_value(row.data_status), "confidence": row.confidence, "evidence": _evidence("demand_elasticity_estimates", row.id, row.quality_metrics)} for row in rows]},
        ), sorted(set(missing))

    def get_seller_price_history_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del offset
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=marketplace)
        stmt = select(ProductPriceHistory).options(joinedload(ProductPriceHistory.product)).where(ProductPriceHistory.seller_id == seller_id)
        stmt = self._filter_by_product_ids(stmt, ProductPriceHistory.product_id, product_ids)
        if marketplace:
            stmt = stmt.where(ProductPriceHistory.marketplace == marketplace)
        stmt = _date_filter(stmt, ProductPriceHistory.changed_at, from_date, to_date)
        rows = self._db.execute(stmt.order_by(ProductPriceHistory.changed_at.desc()).limit(limit)).scalars().all()
        all_rows = self._db.execute(stmt).scalars().all()
        summary = {
            "seller_price_change_count": len(all_rows),
            "products_with_recent_seller_price_changes": len({row.product_id for row in all_rows}),
            "baseline_records_count": sum(1 for row in all_rows if _enum_value(row.source) == "BASELINE_CURRENT_PRICE"),
            "source_table": "product_price_history",
            "competitor_price_history_included": False,
        }
        if not all_rows:
            missing.append("NO_SELLER_PRICE_HISTORY")
        return self._summary_payload(
            summary=summary,
            evidence_tables=("product_price_history", "products"),
            freshness=self._freshness_for_tables(seller_id, ("product_price_history", "products")),
            extra={"latest_price_changes": [_product_price_history_payload(row) for row in rows]},
        ), sorted(set(missing))

    def get_promotion_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del offset
        candidates, _ = self.get_dead_stock_recovery(seller_id=seller_id, product_id=product_id, limit=limit)
        if category:
            candidates = [item for item in candidates if (item.get("product") or {}).get("category") == category]
        active_statuses = [PromotionPlanStatus.PROPOSED, PromotionPlanStatus.APPROVED, PromotionPlanStatus.SCHEDULED, PromotionPlanStatus.RUNNING]
        plan_stmt = select(PromotionPlan).where(PromotionPlan.seller_id == seller_id)
        result_stmt = select(PromotionResult).where(PromotionResult.seller_id == seller_id)
        if product_id:
            plan_stmt = plan_stmt.where(PromotionPlan.product_id == product_id)
            result_stmt = result_stmt.where(PromotionResult.product_id == product_id)
        if marketplace:
            plan_stmt = plan_stmt.where(PromotionPlan.marketplace == marketplace)
            result_stmt = result_stmt.where(PromotionResult.marketplace == marketplace)
        if category:
            plan_stmt = plan_stmt.where(PromotionPlan.category == category)
        plan_stmt = _date_filter(plan_stmt, PromotionPlan.planned_start_at, from_date, to_date)
        result_stmt = _date_filter(result_stmt, PromotionResult.started_at, from_date, to_date)
        active_plans = self._count_rows(select(func.count()).select_from(plan_stmt.where(PromotionPlan.status.in_(active_statuses)).subquery()))
        completed_plans = self._count_rows(select(func.count()).select_from(plan_stmt.where(PromotionPlan.status == PromotionPlanStatus.COMPLETED).subquery()))
        result_count = self._count_rows(select(func.count()).select_from(result_stmt.subquery()))
        partial_results = self._count_rows(select(func.count()).select_from(result_stmt.where(PromotionResult.result_status != "CALCULATED").subquery()))
        missing = ["MISSING_PROMOTION_RESULTS"] if active_plans and not result_count else []
        return self._summary_payload(
            summary={
                "active_planned_promotions": active_plans,
                "completed_promotions": completed_plans,
                "promotion_results": result_count,
                "partial_or_missing_result_count": partial_results,
                "products_suitable_for_promotion": len(candidates),
                "missing_promotion_persistence_warning": False,
                "marketplace_execution_enabled": False,
            },
            evidence_tables=("promotion_plans", "promotion_results", "dead_stock_recovery_recommendations"),
            freshness=self._freshness_for_tables(seller_id, ("promotion_plans", "promotion_results", "dead_stock_recovery_recommendations")),
            extra={"top_candidates": candidates[:limit]},
        ), missing

    def get_promotion_outcome_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del offset
        stmt = select(PromotionResult).options(joinedload(PromotionResult.product), joinedload(PromotionResult.promotion_plan)).where(PromotionResult.seller_id == seller_id)
        if product_id:
            stmt = stmt.where(PromotionResult.product_id == product_id)
        if marketplace:
            stmt = stmt.where(PromotionResult.marketplace == marketplace)
        if category:
            stmt = stmt.join(Product, Product.id == PromotionResult.product_id).where(Product.seller_id == seller_id, Product.category == category)
        stmt = _date_filter(stmt, PromotionResult.started_at, from_date, to_date)
        rows = self._db.execute(stmt).scalars().all()
        revenue = _sum_decimal(row.gross_revenue for row in rows)
        profit = _sum_decimal(row.estimated_profit for row in rows)
        spend = _sum_decimal(row.spend for row in rows)
        top = sorted([row for row in rows if row.roi is not None], key=lambda row: row.roi, reverse=True)[:limit]
        bottom = sorted([row for row in rows if row.roi is not None], key=lambda row: row.roi)[:limit]
        summary = {
            "completed_promotion_result_count": sum(1 for row in rows if _enum_value(row.result_status) == "CALCULATED"),
            "partial_or_missing_outcome_count": sum(1 for row in rows if _enum_value(row.result_status) != "CALCULATED"),
            "gross_revenue": revenue,
            "estimated_profit": profit,
            "spend": spend,
            "roi_available_count": sum(1 for row in rows if row.roi is not None),
        }
        missing = []
        if rows and not any(row.roi is not None for row in rows):
            missing.append("MISSING_PROMOTION_ROI_INPUTS")
        if not rows:
            missing.append("NO_PROMOTION_RESULTS")
        return self._summary_payload(
            summary=summary,
            evidence_tables=("promotion_results", "promotion_plans"),
            freshness=self._freshness_for_tables(seller_id, ("promotion_results", "promotion_plans")),
            extra={"top_performing_promotions": [_promotion_result_payload(row) for row in top], "underperforming_promotions": [_promotion_result_payload(row) for row in bottom]},
        ), missing

    def get_promotion_plans(self, *, seller_id: UUID, product_id: UUID | None, status: str | None, marketplace: str | None, from_date: date | None, to_date: date | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        stmt = select(PromotionPlan).options(joinedload(PromotionPlan.product)).where(PromotionPlan.seller_id == seller_id)
        if product_id:
            stmt = stmt.where(PromotionPlan.product_id == product_id)
        if status:
            stmt = stmt.where(PromotionPlan.status == status)
        if marketplace:
            stmt = stmt.where(PromotionPlan.marketplace == marketplace)
        stmt = _date_filter(stmt, PromotionPlan.planned_start_at, from_date, to_date)
        rows = self._db.execute(stmt.order_by(PromotionPlan.created_at.desc()).limit(limit).offset(offset)).scalars().all()
        payload_rows = [_promotion_plan_payload(row) for row in rows]
        return {
            "rows": payload_rows,
            "pagination": {"limit": limit, "offset": offset, "has_next": len(payload_rows) == limit},
            "freshness": self._freshness_for_tables(seller_id, ("promotion_plans",)),
            "evidence": [_evidence("promotion_plans", row.id) for row in rows],
        }, _missing_if_empty(payload_rows, "No promotion plans were found.")

    def get_promotion_results(self, *, seller_id: UUID, product_id: UUID | None, status: str | None, marketplace: str | None, from_date: date | None, to_date: date | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        stmt = select(PromotionResult).options(joinedload(PromotionResult.product), joinedload(PromotionResult.promotion_plan)).where(PromotionResult.seller_id == seller_id)
        if product_id:
            stmt = stmt.where(PromotionResult.product_id == product_id)
        if status:
            stmt = stmt.where(PromotionResult.result_status == status)
        if marketplace:
            stmt = stmt.where(PromotionResult.marketplace == marketplace)
        stmt = _date_filter(stmt, PromotionResult.started_at, from_date, to_date)
        rows = self._db.execute(stmt.order_by(PromotionResult.started_at.desc()).limit(limit).offset(offset)).scalars().all()
        payload_rows = [_promotion_result_payload(row) for row in rows]
        return {
            "rows": payload_rows,
            "pagination": {"limit": limit, "offset": offset, "has_next": len(payload_rows) == limit},
            "freshness": self._freshness_for_tables(seller_id, ("promotion_results",)),
            "evidence": [_evidence("promotion_results", row.id, row.evidence_json) for row in rows],
        }, _missing_if_empty(payload_rows, "No promotion results were found.")

    def compare_promotion_performance(self, *, seller_id: UUID, product_id: UUID | None, marketplace: str | None, from_date: date | None, to_date: date | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del limit, offset
        stmt = select(PromotionResult).where(PromotionResult.seller_id == seller_id)
        if product_id:
            stmt = stmt.where(PromotionResult.product_id == product_id)
        if marketplace:
            stmt = stmt.where(PromotionResult.marketplace == marketplace)
        stmt = _date_filter(stmt, PromotionResult.started_at, from_date, to_date)
        rows = self._db.execute(stmt).scalars().all()
        revenue = _sum_decimal(getattr(row, "gross_revenue", None) for row in rows)
        profit = _sum_decimal(getattr(row, "estimated_profit", None) for row in rows)
        spend = _sum_decimal(getattr(row, "spend", None) for row in rows)
        discount_cost = _sum_decimal(getattr(row, "discount_cost", None) for row in rows)
        total_cost = (spend or Decimal("0")) + (discount_cost or Decimal("0"))
        roi = profit / total_cost if profit is not None and total_cost else None
        missing = []
        if rows and roi is None:
            missing.append("MISSING_COST_FEE_OR_SPEND_FOR_ROI")
        top = sorted([row for row in rows if row.roi is not None], key=lambda row: row.roi, reverse=True)[:5]
        bottom = sorted([row for row in rows if row.roi is not None], key=lambda row: row.roi)[:5]
        return self._summary_payload(
            summary={"promotion_result_count": len(rows), "gross_revenue": revenue, "estimated_profit": profit, "spend": spend, "discount_cost": discount_cost, "roi": roi},
            evidence_tables=("promotion_results",),
            freshness=self._freshness_for_tables(seller_id, ("promotion_results",)),
            extra={"top_performing_promotions": [_promotion_result_payload(row) for row in top], "underperforming_promotions": [_promotion_result_payload(row) for row in bottom], "marketplace_execution_enabled": False},
        ), missing or _missing_if_empty(rows, "No promotion results were found.")

    def get_price_history(self, *, seller_id: UUID, product_id: UUID | None, marketplace: str | None, from_date: date | None, to_date: date | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        stmt = select(ProductPriceHistory).options(joinedload(ProductPriceHistory.product)).where(ProductPriceHistory.seller_id == seller_id)
        if product_id:
            stmt = stmt.where(ProductPriceHistory.product_id == product_id)
        if marketplace:
            stmt = stmt.where(ProductPriceHistory.marketplace == marketplace)
        stmt = _date_filter(stmt, ProductPriceHistory.changed_at, from_date, to_date)
        rows = self._db.execute(stmt.order_by(ProductPriceHistory.changed_at.desc()).limit(limit).offset(offset)).scalars().all()
        payload_rows = [_product_price_history_payload(row) for row in rows]
        return {
            "source_table": "product_price_history",
            "rows": payload_rows,
            "pagination": {"limit": limit, "offset": offset, "has_next": len(payload_rows) == limit},
            "freshness": self._freshness_for_tables(seller_id, ("product_price_history",)),
            "evidence": [_evidence("product_price_history", row.id) for row in rows],
        }, _missing_if_empty(payload_rows, "No seller product price history records were found.")

    def get_products_with_recent_price_changes(self, *, seller_id: UUID, product_id: UUID | None, marketplace: str | None, from_date: date | None, to_date: date | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        stmt = select(ProductPriceHistory).options(joinedload(ProductPriceHistory.product)).where(ProductPriceHistory.seller_id == seller_id)
        if product_id:
            stmt = stmt.where(ProductPriceHistory.product_id == product_id)
        if marketplace:
            stmt = stmt.where(ProductPriceHistory.marketplace == marketplace)
        stmt = _date_filter(stmt, ProductPriceHistory.changed_at, from_date, to_date)
        rows = self._db.execute(stmt.order_by(ProductPriceHistory.changed_at.desc()).limit(limit).offset(offset)).scalars().all()
        seen: set[UUID] = set()
        products = []
        for row in rows:
            if row.product_id in seen:
                continue
            seen.add(row.product_id)
            products.append({"product": _product_ref(row.product), "latest_price_change": _product_price_history_payload(row)})
        return {
            "source_table": "product_price_history",
            "products": products,
            "pagination": {"limit": limit, "offset": offset, "has_next": len(rows) == limit},
            "freshness": self._freshness_for_tables(seller_id, ("product_price_history",)),
            "evidence": [_evidence("product_price_history", row.id) for row in rows],
        }, _missing_if_empty(products, "No products with seller-side price changes were found.")

    def get_dead_stock_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del marketplace, category, limit, offset
        stmt = select(DeadStockAssessment).where(DeadStockAssessment.seller_id == seller_id)
        if product_id:
            stmt = stmt.where(DeadStockAssessment.product_id == product_id)
        stmt = _date_filter(stmt, DeadStockAssessment.assessed_at, from_date, to_date)
        rows = self._db.execute(stmt).scalars().all()
        estimates = self._db.execute(select(DeadStockCapitalRecoveryEstimate).where(DeadStockCapitalRecoveryEstimate.seller_id == seller_id)).scalars().all()
        locked_values = [Decimal(item.locked_capital) for item in estimates if item.locked_capital is not None]
        recovery_values = [Decimal(item.gross_recovered_cash) for item in estimates if item.gross_recovered_cash is not None]
        missing = []
        if not locked_values and rows:
            missing.append("MISSING_LOCKED_CAPITAL")
        summary = {
            "dead_stock_product_count": sum(1 for row in rows if _enum_value(row.classification) == "DEAD_STOCK"),
            "at_risk_product_count": sum(1 for row in rows if _enum_value(row.classification) == "AT_RISK"),
            "locked_capital": sum(locked_values, Decimal("0")) if locked_values else None,
            "capital_recovery_estimate": sum(recovery_values, Decimal("0")) if recovery_values else None,
            "missing_cost_or_fee_warnings": missing,
        }
        return self._summary_payload(summary=summary, evidence_tables=("dead_stock_assessments", "dead_stock_capital_recovery_estimates"), freshness=self._freshness_for_tables(seller_id, ("dead_stock_assessments", "dead_stock_capital_recovery_estimates"))), missing

    def get_visibility_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del limit, offset
        filters = {"category": category, "marketplace": marketplace}
        if product_id:
            filters["product_id"] = product_id
        product_ids = [row[0] for row in self._db.execute(self._product_statement(seller_id=seller_id, filters=filters).with_only_columns(Product.id)).all()]
        stmt = select(ProductVisibilityMetric).where(ProductVisibilityMetric.seller_id == seller_id)
        if product_ids:
            stmt = stmt.where(ProductVisibilityMetric.product_id.in_(product_ids))
        if marketplace:
            stmt = stmt.where(ProductVisibilityMetric.marketplace == marketplace)
        stmt = _date_filter(stmt, ProductVisibilityMetric.metric_date, from_date, to_date)
        rows = self._db.execute(stmt).scalars().all()
        visible_ids = {row.product_id for row in rows}
        low_visibility = sum(1 for row in rows if (row.listing_quality_score is not None and row.listing_quality_score < 50) or row.impressions == 0)
        quality_issues = sum(1 for row in rows if row.listing_quality_score is not None and row.listing_quality_score < 70)
        missing = [] if rows else ["VISIBILITY_DATA_UNAVAILABLE"]
        summary = {
            "products_with_visibility_data": len(visible_ids),
            "products_with_missing_visibility_data": max(0, len(product_ids) - len(visible_ids)),
            "low_visibility_count": low_visibility if rows else None,
            "listing_quality_issues": quality_issues,
        }
        return self._summary_payload(summary=summary, evidence_tables=("product_visibility_metrics", "products"), freshness=self._freshness_for_tables(seller_id, ("product_visibility_metrics", "products"))), missing

    def get_alert_recommendation_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del marketplace, category, limit, offset
        alert_stmt = select(Alert).where(Alert.seller_id == seller_id)
        rec_stmt = select(Recommendation).join(Product, Product.id == Recommendation.product_id).where(Product.seller_id == seller_id)
        if product_id:
            alert_stmt = alert_stmt.where(Alert.product_id == product_id)
            rec_stmt = rec_stmt.where(Recommendation.product_id == product_id)
        alert_stmt = _date_filter(alert_stmt, Alert.created_at, from_date, to_date)
        rec_stmt = _date_filter(rec_stmt, Recommendation.created_at, from_date, to_date)
        summary = {
            "unresolved_alert_count": self._count_rows(select(func.count()).select_from(alert_stmt.where(Alert.read_at.is_(None)).subquery())),
            "pending_recommendation_count": self._count_rows(select(func.count()).select_from(rec_stmt.subquery())),
            "open_reorder_recommendation_count": self._count_rows(select(func.count()).select_from(ReorderRecommendation).where(ReorderRecommendation.seller_id == seller_id, ReorderRecommendation.recommendation_status == ReorderRecommendationStatus.OPEN)),
            "open_pricing_recommendation_count": self._count_rows(select(func.count()).select_from(DynamicPricingRecommendation).where(DynamicPricingRecommendation.seller_id == seller_id, DynamicPricingRecommendation.recommendation_status == DynamicPricingRecommendationStatus.OPEN)),
        }
        return self._summary_payload(summary=summary, evidence_tables=("alerts", "recommendations", "reorder_recommendations", "dynamic_pricing_recommendations"), freshness=self._freshness_for_tables(seller_id, ("alerts", "recommendations", "reorder_recommendations", "dynamic_pricing_recommendations"))), []

    def get_alert_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del marketplace, offset
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=None)
        stmt = select(Alert).options(joinedload(Alert.product)).where(Alert.seller_id == seller_id)
        stmt = self._filter_by_product_ids(stmt, Alert.product_id, product_ids)
        stmt = _date_filter(stmt, Alert.created_at, from_date, to_date)
        rows = self._db.execute(stmt).scalars().all()
        unresolved = [row for row in rows if row.read_at is None or row.delivery_status != AlertDeliveryStatus.delivered]
        top = sorted(unresolved, key=lambda row: (_urgency_rank(row.urgency_level), row.created_at), reverse=True)[:limit]
        summary = {
            "unresolved_alert_count": len(unresolved),
            "alerts_by_severity": _counts_by(rows, "urgency_level"),
            "alerts_by_domain": _counts_by(rows, "alert_type"),
            "undelivered_alert_count": sum(1 for row in rows if row.delivery_status != AlertDeliveryStatus.delivered),
        }
        if not rows:
            missing.append("NO_ALERT_DATA")
        return self._summary_payload(
            summary=summary,
            evidence_tables=("alerts", "products"),
            freshness=self._freshness_for_tables(seller_id, ("alerts", "products")),
            extra={"urgent_affected_products": [_alert_action_payload(row) for row in top]},
        ), sorted(set(missing))

    def get_recommendation_summary(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, marketplace: str | None, category: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        del marketplace, offset
        self._sync_action_center_items(seller_id=seller_id)
        product_ids, missing = self._scoped_product_ids(seller_id=seller_id, product_id=product_id, category=category, marketplace=None)
        generic_stmt = select(Recommendation).options(joinedload(Recommendation.product)).join(Product, Product.id == Recommendation.product_id).where(Product.seller_id == seller_id)
        if product_ids:
            generic_stmt = generic_stmt.where(Recommendation.product_id.in_(product_ids))
        generic_stmt = _date_filter(generic_stmt, Recommendation.created_at, from_date, to_date)
        generic = self._db.execute(generic_stmt).scalars().all()
        reorder_stmt = select(ReorderRecommendation).options(joinedload(ReorderRecommendation.product)).where(ReorderRecommendation.seller_id == seller_id)
        reorder_stmt = self._filter_by_product_ids(reorder_stmt, ReorderRecommendation.product_id, product_ids)
        dynamic_stmt = select(DynamicPricingRecommendation).options(joinedload(DynamicPricingRecommendation.product)).where(DynamicPricingRecommendation.seller_id == seller_id)
        dynamic_stmt = self._filter_by_product_ids(dynamic_stmt, DynamicPricingRecommendation.product_id, product_ids)
        dead_stmt = select(DeadStockRecoveryRecommendation).options(joinedload(DeadStockRecoveryRecommendation.product)).where(DeadStockRecoveryRecommendation.seller_id == seller_id)
        dead_stmt = self._filter_by_product_ids(dead_stmt, DeadStockRecoveryRecommendation.product_id, product_ids)
        action_stmt = select(ActionCenterItem).where(ActionCenterItem.seller_id == seller_id)
        action_stmt = self._filter_by_product_ids(action_stmt, ActionCenterItem.product_id, product_ids)
        open_actions = self._db.execute(action_stmt.where(ActionCenterItem.status == ActionCenterItemStatus.OPEN).order_by(ActionCenterItem.priority.desc(), ActionCenterItem.due_at.asc().nullslast(), ActionCenterItem.created_at.desc()).limit(limit)).scalars().all()
        summary = {
            "pending_recommendations_by_source": {
                "recommendations": len(generic),
                "reorder_recommendations": self._count_rows(select(func.count()).select_from(reorder_stmt.where(ReorderRecommendation.recommendation_status == ReorderRecommendationStatus.OPEN).subquery())),
                "dynamic_pricing_recommendations": self._count_rows(select(func.count()).select_from(dynamic_stmt.where(DynamicPricingRecommendation.recommendation_status == DynamicPricingRecommendationStatus.OPEN).subquery())),
                "dead_stock_recovery_recommendations": self._count_rows(select(func.count()).select_from(dead_stmt.where(DeadStockRecoveryRecommendation.recommendation_status == DeadStockRecoveryRecommendationStatus.OPEN).subquery())),
            },
            "open_action_center_items": len(open_actions),
        }
        return self._summary_payload(
            summary=summary,
            evidence_tables=("recommendations", "reorder_recommendations", "dynamic_pricing_recommendations", "dead_stock_recovery_recommendations", "action_center_items"),
            freshness=self._freshness_for_tables(seller_id, ("recommendations", "reorder_recommendations", "dynamic_pricing_recommendations", "dead_stock_recovery_recommendations", "action_center_items")),
            extra={"top_prioritized_actions": [_action_center_payload(row) for row in open_actions]},
        ), sorted(set(missing))

    def count_products(self, *, seller_id: UUID, filters: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        missing = self._unsupported_filter_notes(filters)
        count = self._product_count(seller_id=seller_id, filters=filters)
        return {
            "count": count,
            "filters_used": _clean_filter_payload(filters),
            "evidence": [_evidence("products", "seller_scope", {"filters": _clean_filter_payload(filters)})],
        } | self._listing_summary(seller_id=seller_id, filters=filters, listed_count=count), missing

    def list_products(self, *, seller_id: UUID, filters: dict[str, Any], sort_by: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        statement = self._product_statement(seller_id=seller_id, filters=filters)
        total = int(self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one() or 0)
        statement = self._sort_products(statement, sort_by).limit(limit).offset(offset)
        rows = self._db.execute(statement).scalars().all()
        product_ids = [row.id for row in rows]
        listings_by_product = self._listings_by_product(seller_id=seller_id, product_ids=product_ids)
        fee_ids = self._product_ids_with_fee_policy(seller_id=seller_id, product_ids=product_ids)
        pricing_ids = self._product_ids_with_pricing_policy(seller_id=seller_id, product_ids=product_ids)
        sold_ids = self._product_ids_with_sales(seller_id=seller_id, product_ids=product_ids)
        products = [
            self._product_payload(
                row,
                listings=listings_by_product.get(row.id, []),
                has_fee_policy=row.id in fee_ids,
                has_pricing_policy=row.id in pricing_ids,
                has_sales=row.id in sold_ids,
            )
            for row in rows
        ]
        return {
            "products": products,
            "pagination": {"total": total, "limit": limit, "offset": offset, "has_next": offset + limit < total},
            "filters_used": _clean_filter_payload(filters),
            "evidence": [_evidence("products", "seller_scope", {"product_ids": [str(item.id) for item in rows]})],
        } | self._listing_summary(seller_id=seller_id, filters=filters, listed_count=total), self._unsupported_filter_notes(filters, seller_id=seller_id, product_ids=product_ids)

    def _listing_summary(self, *, seller_id: UUID, filters: dict[str, Any], listed_count: int) -> dict[str, Any]:
        """Sellers say "listed" for products in their account; the filter means an active marketplace listing.

        Without the account total, a seller with products but no listing rows was told they have no products.
        """
        if not filters.get("listed"):
            return {}
        unlisted_filters = {key: value for key, value in filters.items() if key != "listed"}
        total = self._product_count(seller_id=seller_id, filters=unlisted_filters)
        return {
            "listing_summary": {
                "total_products_in_account": total,
                "products_with_active_marketplace_listing": listed_count,
                "how_to_answer": (
                    f"Sellers usually mean products in their account: state that they have {total} products first, "
                    f"then that {listed_count} of them are linked to an active marketplace listing."
                ),
            }
        }

    def search_products(self, *, seller_id: UUID, query: str, category: str | None, marketplace: str | None, limit: int) -> tuple[dict[str, Any], list[str]]:
        filters = {"category": category, "marketplace": marketplace}
        statement = self._product_statement(seller_id=seller_id, filters=filters)
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            (Product.title.ilike(pattern))
            | (Product.category.ilike(pattern))
            | (Product.searchable_text.ilike(pattern))
        ).order_by(Product.title.asc(), Product.created_at.desc()).limit(limit)
        rows = self._db.execute(statement).scalars().all()
        normalized = query.casefold().strip()
        exact = [row for row in rows if row.title.casefold() == normalized]
        confidence = "HIGH" if len(exact) == 1 else "MEDIUM" if rows else "NO_CONTEXT"
        ambiguity = None
        if len(rows) > 1 and not exact:
            ambiguity = "Multiple seller-owned products match this query. Ask the seller to choose a product."
        return {
            "products": [self._product_ref_with_setup(row, listings=self._listings_for_product(seller_id=seller_id, product_id=row.id)) for row in rows],
            "confidence": confidence,
            "ambiguity_warning": ambiguity,
            "evidence": [_evidence("products", "seller_scope", {"query": query, "matched_product_ids": [str(row.id) for row in rows]})],
        }, self._unsupported_filter_notes(filters, seller_id=seller_id, product_ids=[row.id for row in rows])

    def get_product_profile(self, *, seller_id: UUID, product_id: UUID) -> tuple[dict[str, Any], list[str]]:
        product = self._db.execute(select(Product).where(Product.seller_id == seller_id, Product.id == product_id)).scalar_one_or_none()
        if product is None:
            raise ProductAccessError("Product does not belong to the authenticated seller.")
        inventory_age = self._latest_row(InventoryAgingSnapshot, seller_id=seller_id, product_id=product_id, order_column=InventoryAgingSnapshot.calculated_at)
        last_sale = self._db.execute(
            select(SalesRecord)
            .where(
                SalesRecord.seller_id == seller_id,
                SalesRecord.product_id == product_id,
                SalesRecord.status.in_([SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED]),
                SalesRecord.is_test_order.is_(False),
            )
            .order_by(SalesRecord.sold_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        sales_velocity = self._latest_row(SalesVelocity, seller_id=seller_id, product_id=product_id, order_column=SalesVelocity.calculated_at)
        pricing = self._latest_row(DynamicPricingRecommendation, seller_id=seller_id, product_id=product_id, order_column=DynamicPricingRecommendation.generated_at)
        inventory_risk = self._latest_row(InventoryRiskAssessment, seller_id=seller_id, product_id=product_id, order_column=InventoryRiskAssessment.assessed_at)
        dead_stock = self._latest_row(DeadStockAssessment, seller_id=seller_id, product_id=product_id, order_column=DeadStockAssessment.assessed_at)
        visibility = self._latest_row(ProductVisibilityMetric, seller_id=seller_id, product_id=product_id, order_column=ProductVisibilityMetric.metric_date)
        listings = self._listings_for_product(seller_id=seller_id, product_id=product_id)
        primary_listing = _primary_listing(listings)
        competitor_count = self._count_rows(select(func.count()).select_from(Competitor).where(Competitor.product_id == product_id))
        threat = self._latest_row(CompetitorEvent, seller_id=seller_id, product_id=product_id, order_column=CompetitorEvent.detected_at)
        has_fee = self._has_fee_policy(seller_id=seller_id, product_id=product_id, category=product.category)
        has_pricing = self._has_pricing_policy(seller_id=seller_id, product_id=product_id)
        revenue_summary = self._revenue_total(seller_id=seller_id, product_id=product_id, from_date=None, to_date=None)
        missing = self._missing_setup_for_product(product, has_fee_policy=has_fee, has_pricing_policy=has_pricing)
        if not listings:
            missing.append("MISSING_MARKETPLACE")
        if inventory_age is None:
            missing.append("Inventory age source is unavailable.")
        if last_sale is None:
            missing.append("No completed/fulfilled sales history was found for this product.")
        if visibility is None:
            missing.append("Visibility data is unavailable; do not treat this as low visibility.")
        margin = None
        if product.cost_price is not None and product.selling_price is not None and has_fee:
            margin = {
                "unit_contribution_before_marketplace_fees": product.selling_price - product.cost_price,
                "margin_rate_before_marketplace_fees": _safe_ratio(product.selling_price - product.cost_price, product.selling_price),
                "fee_policy_present": True,
            }
        else:
            missing.append("Estimated margin is unavailable until cost, selling price, and fee policy are present.")
        return {
            "product": {
                "id": str(product.id),
                "name": product.title,
                "sku": product.sku,
                "category": product.category,
                "marketplace": primary_listing.marketplace if primary_listing else None,
                "status": _enum_value(product.status),
                "selling_price": primary_listing.selling_price if primary_listing and primary_listing.selling_price is not None else product.selling_price,
                "cost_or_landed_cost": product.cost_price,
                "currency": primary_listing.currency if primary_listing else None,
                "updated_at": product.updated_at,
                "marketplace_listings": [_listing_payload(listing) for listing in listings],
                "current_stock": product.stock_quantity,
                "inventory_age": _inventory_age_payload(inventory_age),
                "last_sale": _last_sale_payload(last_sale),
                "sales_velocity": _sales_velocity_payload(sales_velocity),
                "revenue_summary": {"gross_revenue": revenue_summary},
                "estimated_margin": margin,
                "competitor_count": competitor_count,
                "latest_competitor_threat": _competitor_threat_payload(threat),
                "latest_pricing_recommendation": _pricing_payload(pricing),
                "latest_inventory_risk": _inventory_risk_payload(inventory_risk),
                "latest_dead_stock_status": _dead_stock_payload(dead_stock),
                "latest_visibility_status": _visibility_payload(visibility),
                "missing_setup_data": missing,
            },
            "evidence": [
                _evidence("products", product.id),
                *[_evidence("product_marketplace_listings", listing.id) for listing in listings],
                *[_evidence(table, source_id) for table, source_id in (
                    ("inventory_aging_snapshots", getattr(inventory_age, "id", None)),
                    ("sales_records", getattr(last_sale, "id", None)),
                    ("sales_velocity", getattr(sales_velocity, "id", None)),
                    ("competitor_events", getattr(threat, "id", None)),
                    ("dynamic_pricing_recommendations", getattr(pricing, "id", None)),
                    ("inventory_risk_assessments", getattr(inventory_risk, "id", None)),
                    ("dead_stock_assessments", getattr(dead_stock, "id", None)),
                    ("product_visibility_metrics", getattr(visibility, "id", None)),
                ) if source_id],
            ],
        }, missing

    def get_products_missing_setup(self, *, seller_id: UUID, setup_type: str | None, category: str | None, marketplace: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        filters = {"category": category, "marketplace": marketplace}
        all_missing_filters = _filters_for_setup_type(setup_type)
        statement = self._product_statement(seller_id=seller_id, filters=filters)
        rows = self._db.execute(statement.order_by(Product.created_at.desc(), Product.id.desc()).limit(200)).scalars().all()
        product_ids = [row.id for row in rows]
        listings_by_product = self._listings_by_product(seller_id=seller_id, product_ids=product_ids)
        fee_ids = self._product_ids_with_fee_policy(seller_id=seller_id, product_ids=product_ids)
        pricing_ids = self._product_ids_with_pricing_policy(seller_id=seller_id, product_ids=product_ids)
        sales_ids = self._product_ids_with_sales(seller_id=seller_id, product_ids=product_ids)
        visibility_ids = self._product_ids_with_visibility(seller_id=seller_id, product_ids=product_ids)
        aging_ids = self._product_ids_with_inventory_age(seller_id=seller_id, product_ids=product_ids)
        items = []
        for product in rows:
            missing_fields = self._missing_setup_for_product(product, has_fee_policy=product.id in fee_ids, has_pricing_policy=product.id in pricing_ids)
            if not listings_by_product.get(product.id):
                missing_fields.append("MISSING_MARKETPLACE")
            if product.id not in sales_ids:
                missing_fields.append("SALES_HISTORY")
            if product.id not in visibility_ids:
                missing_fields.append("VISIBILITY_DATA")
            if product.id not in aging_ids:
                missing_fields.append("INVENTORY_AGE_SOURCE")
            if all_missing_filters and not set(missing_fields).intersection(all_missing_filters):
                continue
            if not missing_fields:
                continue
            items.append(
                {
                    "product": _product_ref(product),
                    "missing_setup_fields": missing_fields,
                    "next_actions": [_next_action_for_setup(field) for field in missing_fields],
                    "evidence": _evidence("products", product.id),
                }
            )
        total = len(items)
        paged = items[offset : offset + limit]
        return {
            "products": paged,
            "pagination": {"total": total, "limit": limit, "offset": offset, "has_next": offset + limit < total},
            "filters_used": _clean_filter_payload({"setup_type": setup_type, **filters}),
            "evidence": [_evidence("products", "seller_scope", {"product_ids": [item["product"]["id"] for item in paged]})],
        }, self._unsupported_filter_notes(filters, seller_id=seller_id, product_ids=[item["product"]["id"] for item in paged])

    def get_revenue_summary(self, *, seller_id: UUID, from_date: date, to_date: date, marketplace: str | None, product_id: UUID | None, category: str | None, compare_to_previous_period: bool) -> tuple[dict[str, Any], list[str]]:
        return SalesRevenueAnalyticsService(self._db).get_revenue_summary(
            seller_id=seller_id,
            from_date=from_date,
            to_date=to_date,
            marketplace=marketplace,
            product_id=product_id,
            category=category,
            compare_to_previous_period=compare_to_previous_period,
        )

    def get_sales_trends(self, *, seller_id: UUID, from_date: date, to_date: date, granularity: str, marketplace: str | None, product_id: UUID | None, category: str | None) -> tuple[dict[str, Any], list[str]]:
        return SalesRevenueAnalyticsService(self._db).get_sales_trends(
            seller_id=seller_id,
            from_date=from_date,
            to_date=to_date,
            granularity=granularity,
            marketplace=marketplace,
            product_id=product_id,
            category=category,
        )

    def get_profit_summary(self, *, seller_id: UUID, from_date: date, to_date: date, marketplace: str | None, product_id: UUID | None, category: str | None) -> tuple[dict[str, Any], list[str]]:
        return ProfitMarginAnalyticsService(self._db).get_profit_summary(
            seller_id=seller_id,
            from_date=from_date,
            to_date=to_date,
            marketplace=marketplace,
            product_id=product_id,
            category=category,
        )

    def explain_revenue_change_deterministic(self, *, seller_id: UUID, from_date: date, to_date: date, compare_to_previous_period: bool, marketplace: str | None, product_id: UUID | None, category: str | None) -> tuple[dict[str, Any], list[str]]:
        return BusinessChangeAnalyticsService(self._db).explain_revenue_change(
            seller_id=seller_id,
            from_date=from_date,
            to_date=to_date,
            compare_to_previous_period=compare_to_previous_period,
            marketplace=marketplace,
            product_id=product_id,
            category=category,
        )

    def get_top_products_by_revenue(self, *, seller_id: UUID, from_date: date, to_date: date, limit: int, category: str | None, marketplace: str | None) -> tuple[dict[str, Any], list[str]]:
        return SalesRevenueAnalyticsService(self._db).get_top_products_by_revenue(
            seller_id=seller_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            category=category,
            marketplace=marketplace,
        )

    def get_products_with_no_sales(self, *, seller_id: UUID, since_date: date | None, category: str | None, marketplace: str | None, limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        return SalesRevenueAnalyticsService(self._db).get_products_with_no_sales(
            seller_id=seller_id,
            since_date=since_date,
            category=category,
            marketplace=marketplace,
            limit=limit,
            offset=offset,
        )

    def get_today_actions(self, *, seller_id: UUID, product_id: UUID | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
        self._sync_action_center_items(seller_id=seller_id)
        statement = select(ActionCenterItem).where(ActionCenterItem.seller_id == seller_id, ActionCenterItem.status == ActionCenterItemStatus.OPEN)
        statement = _limit_product_query(statement, product_id, ActionCenterItem.product_id)
        action_items = self._db.execute(statement.order_by(ActionCenterItem.priority.desc(), ActionCenterItem.due_at.asc().nullslast(), ActionCenterItem.created_at.desc()).limit(limit)).scalars().all()
        if action_items:
            return [_action_center_payload(item) for item in action_items], []

        rows: list[dict[str, Any]] = []
        rows.extend(self.get_restock_recommendations(seller_id=seller_id, product_id=product_id, category=None, limit=limit)[0])
        if self._table_exists("dynamic_pricing_recommendations"):
            rows.extend(self.get_pricing_recommendations(seller_id=seller_id, product_id=product_id, limit=limit)[0])
        if self._table_exists("dead_stock_recovery_recommendations"):
            rows.extend(self.get_dead_stock_recovery(seller_id=seller_id, product_id=product_id, limit=limit)[0])
        if self._table_exists("market_opportunities"):
            opportunities = self._db.execute(
                _limit_product_query(
                    select(MarketOpportunity).options(joinedload(MarketOpportunity.product)).where(MarketOpportunity.seller_id == seller_id, MarketOpportunity.status == MarketOpportunityStatus.OPEN),
                    product_id,
                    MarketOpportunity.product_id,
                ).order_by(MarketOpportunity.opportunity_score.desc(), MarketOpportunity.detected_at.desc()).limit(limit)
            ).scalars().all()
            for item in opportunities:
                rows.append(
                    {
                        "action_type": _enum_value(item.recommended_action),
                        "product": _product_ref(item.product),
                        "expected_impact": {"estimated_revenue": item.estimated_revenue, "currency": item.estimated_revenue_currency},
                        "urgency": _enum_value(item.opportunity_level),
                        "confidence": item.confidence_score,
                        "evidence": _evidence("market_opportunities", item.id, item.evidence),
                    }
                )
        rows = sorted(rows, key=lambda row: (_urgency_rank(row.get("urgency")), _decimal(row.get("confidence"))), reverse=True)[:limit]
        return rows, _missing_if_empty(rows, "No open action candidates were found.")

    def get_restock_recommendations(self, *, seller_id: UUID, product_id: UUID | None, category: str | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
        has_stockout_predictions = self._table_exists("stockout_predictions")
        options = [joinedload(ReorderRecommendation.product)]
        if has_stockout_predictions:
            options.append(joinedload(ReorderRecommendation.stockout_prediction))
        statement = select(ReorderRecommendation).options(*options).where(
            ReorderRecommendation.seller_id == seller_id,
            ReorderRecommendation.recommendation_status == ReorderRecommendationStatus.OPEN,
            ReorderRecommendation.action == ReorderRecommendationAction.REORDER,
            ReorderRecommendation.recommended_quantity > 0,
        )
        statement = _limit_product_query(statement, product_id, ReorderRecommendation.product_id)
        if category:
            statement = statement.join(Product, Product.id == ReorderRecommendation.product_id).where(Product.category == category, Product.seller_id == seller_id)
        rows = self._db.execute(statement.order_by(ReorderRecommendation.reorder_deadline.asc().nullslast(), ReorderRecommendation.confidence_score.desc()).limit(limit)).scalars().all()
        payload = [
            {
                "action_type": "REORDER",
                "product": _product_ref(row.product),
                "current_stock": row.inventory_position,
                "sales_velocity": row.daily_sales_rate,
                "days_remaining": getattr(row.stockout_prediction, "days_remaining", None) if has_stockout_predictions else None,
                "supplier_lead_time": row.supplier_lead_time_days,
                "reorder_quantity": row.recommended_quantity,
                "risk_level": _risk_from_reorder(row),
                "urgency": _risk_from_reorder(row),
                "confidence": row.confidence_score,
                "evidence": _evidence("reorder_recommendations", row.id, row.evidence),
            }
            for row in rows
        ]
        return payload, _missing_if_empty(payload, "No reorder recommendations were found.")

    def get_inventory_risks(self, *, seller_id: UUID, product_id: UUID | None, risk_level: str | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
        statement = select(InventoryRiskAssessment).options(joinedload(InventoryRiskAssessment.product), joinedload(InventoryRiskAssessment.stockout_prediction)).where(InventoryRiskAssessment.seller_id == seller_id)
        statement = _limit_product_query(statement, product_id, InventoryRiskAssessment.product_id)
        if risk_level:
            statement = statement.where(InventoryRiskAssessment.risk_level == InventoryRiskLevel(risk_level))
        rows = self._db.execute(statement.order_by(InventoryRiskAssessment.risk_score.desc(), InventoryRiskAssessment.assessed_at.desc()).limit(limit)).scalars().all()
        payload = [
            {
                "product": _product_ref(row.product),
                "risk_level": _enum_value(row.risk_level),
                "stockout_prediction": _stockout_payload(row.stockout_prediction),
                "velocity": getattr(row.stockout_prediction, "daily_sales_rate", None),
                "confidence": row.confidence_score,
                "evidence": _evidence("inventory_risk_assessments", row.id, row.factors),
            }
            for row in rows
        ]
        return payload, _missing_if_empty(payload, "No inventory risk assessments were found.")

    def explain_revenue_drop(self, *, seller_id: UUID, product_id: UUID | None, from_date: date, to_date: date, compare_to_previous_period: bool) -> tuple[dict[str, Any], list[str]]:
        payload, missing = self.explain_revenue_change_deterministic(
            seller_id=seller_id,
            product_id=product_id,
            from_date=from_date,
            to_date=to_date,
            compare_to_previous_period=compare_to_previous_period,
            category=None,
            marketplace=None,
        )
        return {
            "revenue_change": {
                "current_period_revenue": payload.get("current_period_revenue"),
                "previous_period_revenue": payload.get("previous_period_revenue"),
                "absolute_change": payload.get("revenue_delta"),
                "percent_change": payload.get("percentage_change"),
            },
            "likely_factors": payload.get("likely_factors", []),
            "evidence_by_source": {"deterministic_analytics": payload.get("evidence", [])},
            "confidence": payload.get("confidence", "LOW"),
            "data_completeness": payload.get("data_completeness"),
        }, missing

    def get_competitor_threats(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
        statement = select(CompetitorEvent).options(joinedload(CompetitorEvent.product), joinedload(CompetitorEvent.competitor)).where(CompetitorEvent.seller_id == seller_id)
        statement = _limit_product_query(statement, product_id, CompetitorEvent.product_id)
        if from_date:
            statement = statement.where(CompetitorEvent.detected_at >= _start_of_day(from_date))
        if to_date:
            statement = statement.where(CompetitorEvent.detected_at <= _end_of_day(to_date))
        events = self._db.execute(statement.order_by(CompetitorEvent.severity.desc(), CompetitorEvent.detected_at.desc()).limit(limit)).scalars().all()
        payload = []
        for event in events:
            ranking = self._latest_ranking(seller_id=seller_id, competitor_id=event.competitor_id, product_id=event.product_id)
            payload.append(
                {
                    "competitor": _competitor_ref(event.competitor),
                    "affected_product": _product_ref(event.product),
                    "price_gap": event.price_change_amount,
                    "stock_status": getattr(event.competitor, "stock_status", None),
                    "ranking": getattr(ranking, "market_rank", None),
                    "threat_reason": _enum_value(event.event_type),
                    "confidence": getattr(event.competitor, "match_confidence", None),
                    "evidence": _evidence("competitor_events", event.id, {"severity": _enum_value(event.severity), "old_value": event.old_value, "new_value": event.new_value}),
                }
            )
        return payload, _missing_if_empty(payload, "No competitor threats were found.")

    def get_pricing_recommendations(self, *, seller_id: UUID, product_id: UUID | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
        statement = select(DynamicPricingRecommendation).options(joinedload(DynamicPricingRecommendation.product)).where(
            DynamicPricingRecommendation.seller_id == seller_id,
            DynamicPricingRecommendation.recommendation_status == DynamicPricingRecommendationStatus.OPEN,
        )
        statement = _limit_product_query(statement, product_id, DynamicPricingRecommendation.product_id)
        rows = self._db.execute(statement.order_by(DynamicPricingRecommendation.generated_at.desc()).limit(limit)).scalars().all()
        payload = [
            {
                "product": _product_ref(row.product),
                "current_price": row.current_price,
                "recommended_price": row.recommended_price,
                "recommended_action": _enum_value(row.action),
                "margin_safety": {"minimum_safe_price": row.minimum_safe_price, "margin_rate": row.margin_rate, "safe": row.minimum_safe_price is None or row.recommended_price >= row.minimum_safe_price},
                "expected_impact": {"revenue": row.revenue_impact, "profit": row.profit_impact},
                "blocked_reasons": [] if row.minimum_safe_price is None or row.recommended_price >= row.minimum_safe_price else ["Recommended price is below MarginGuard minimum safe price."],
                "confidence": row.confidence_score,
                "evidence": _evidence("dynamic_pricing_recommendations", row.id, row.evidence),
            }
            for row in rows
        ]
        return payload, _missing_if_empty(payload, "No pricing recommendations were found.")

    def simulate_price_change(self, *, seller_id: UUID, product_id: UUID, candidate_price: Decimal | None, candidate_discount_rate: Decimal | None, forecast_horizon_days: int) -> tuple[dict[str, Any], list[str]]:
        product = self._db.execute(select(Product).where(Product.seller_id == seller_id, Product.id == product_id)).scalar_one_or_none()
        analytics = self._db.execute(select(PricingAnalyticsSnapshot).where(PricingAnalyticsSnapshot.seller_id == seller_id, PricingAnalyticsSnapshot.product_id == product_id).order_by(PricingAnalyticsSnapshot.calculated_at.desc()).limit(1)).scalar_one_or_none()
        if product is None:
            raise ProductAccessError("Product does not belong to the authenticated seller.")
        price = candidate_price
        if price is None and candidate_discount_rate is not None:
            price = Decimal(product.selling_price) * (Decimal("1") - Decimal(candidate_discount_rate))
        minimum_safe = getattr(analytics, "minimum_safe_price", product.cost_price)
        allowed = price is not None and price >= minimum_safe
        daily_units = getattr(analytics, "daily_sales_rate", None) or Decimal("0")
        expected_units = Decimal(forecast_horizon_days) * Decimal(daily_units)
        expected_revenue = price * expected_units if price is not None else None
        expected_profit = (price - product.cost_price) * expected_units if price is not None else None
        return {
            "allowed": bool(allowed),
            "candidate_price": price,
            "margin_guard": {"minimum_safe_price": minimum_safe, "current_cost": product.cost_price, "safe": bool(allowed)},
            "expected_revenue": expected_revenue if allowed else None,
            "expected_profit": expected_profit if allowed else None,
            "blocked_reasons": [] if allowed else ["Candidate price is below MarginGuard minimum safe price."],
            "evidence": [_evidence("pricing_analytics_snapshots", getattr(analytics, "id", product.id), getattr(analytics, "evidence", {"product_id": str(product.id)}))],
        }, [] if analytics else ["No pricing analytics snapshot was found; simulation used product cost as minimum safety baseline."]

    def get_promotion_recommendations(self, *, seller_id: UUID, product_id: UUID | None, category: str | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
        recovery, missing = self.get_dead_stock_recovery(seller_id=seller_id, product_id=product_id, limit=limit)
        promotions = []
        for item in recovery:
            product = item.get("product") or {}
            if category and product.get("category") != category:
                continue
            action = item.get("recovery_action")
            promotions.append(
                {
                    "promotion_type": action if action in {"BUNDLE", "DISCOUNT", "FLASH_SALE"} else "MANUAL_REVIEW",
                    "product": product,
                    "expected_impact": item.get("potential_recovery_range"),
                    "confidence": item.get("confidence"),
                    "margin_safety": {"execution_enabled": False, "requires_manual_review": True},
                    "evidence": item.get("evidence"),
                }
            )
        if not promotions:
            missing.append("No persisted promotion module exists yet; suggestions are derived from dead-stock recovery signals.")
        return promotions[:limit], missing

    def get_dead_stock_recovery(self, *, seller_id: UUID, product_id: UUID | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
        statement = select(DeadStockRecoveryRecommendation).options(joinedload(DeadStockRecoveryRecommendation.product), joinedload(DeadStockRecoveryRecommendation.dead_stock_assessment)).where(
            DeadStockRecoveryRecommendation.seller_id == seller_id,
            DeadStockRecoveryRecommendation.recommendation_status == DeadStockRecoveryRecommendationStatus.OPEN,
        )
        statement = _limit_product_query(statement, product_id, DeadStockRecoveryRecommendation.product_id)
        rows = self._db.execute(statement.order_by(DeadStockRecoveryRecommendation.generated_at.desc()).limit(limit)).scalars().all()
        payload = [
            {
                "product": _product_ref(row.product),
                "locked_capital": getattr(row.dead_stock_assessment, "eligible_quantity", None) * row.product.cost_price if getattr(row, "dead_stock_assessment", None) and getattr(row, "product", None) else None,
                "classification": _enum_value(getattr(row.dead_stock_assessment, "classification", None)),
                "recovery_action": _enum_value(row.primary_action),
                "potential_recovery_range": {"recommended_price": row.recommended_price, "recommended_discount_rate": row.recommended_discount_rate, "quantity": row.recommended_quantity},
                "confidence": row.confidence_score,
                "evidence": _evidence("dead_stock_recovery_recommendations", row.id, row.evidence),
            }
            for row in rows
        ]
        return payload, _missing_if_empty(payload, "No dead-stock recovery recommendations were found.")

    def get_seo_opportunities(self, *, seller_id: UUID, product_id: UUID | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
        statement = select(ProductVisibilityMetric).options(joinedload(ProductVisibilityMetric.product)).where(ProductVisibilityMetric.seller_id == seller_id)
        statement = _limit_product_query(statement, product_id, ProductVisibilityMetric.product_id)
        rows = self._db.execute(statement.order_by(ProductVisibilityMetric.listing_quality_score.asc().nullsfirst(), ProductVisibilityMetric.metric_date.desc()).limit(limit)).scalars().all()
        payload = [
            {
                "product": _product_ref(row.product),
                "issue": _seo_issue(row),
                "suggested_improvement": _seo_suggestion(row),
                "visibility_evidence": {"impressions": row.impressions, "views": row.views, "clicks": row.clicks, "search_rank": row.search_rank, "listing_quality_score": row.listing_quality_score},
                "confidence": row.listing_quality_score,
                "evidence": _evidence("product_visibility_metrics", row.id, {"metric_date": row.metric_date, "marketplace": row.marketplace}),
            }
            for row in rows
        ]
        return payload, _missing_if_empty(payload, "No listing visibility metrics were found.")

    def retrieve_business_memory(self, *, seller_id: UUID, question: str, product_id: UUID | None, source_types: list[str] | None, from_date: date | None, to_date: date | None, top_k: int) -> tuple[dict[str, Any], list[str]]:
        parsed_source_types = None
        if source_types:
            try:
                parsed_source_types = [RagMemorySourceType(item) for item in source_types]
            except ValueError as exc:
                raise ToolArgumentError("source_types contains an unsupported RAG source type") from exc
        result = RagRetrievalService(self._db).retrieve_context(
            seller_id=seller_id,
            question=question,
            product_id=product_id,
            source_types=parsed_source_types,
            from_event_time=_start_of_day(from_date) if from_date else None,
            to_event_time=_end_of_day(to_date) if to_date else None,
            top_k=top_k,
        )
        return {
            "memory_chunks": [
                {
                    "evidence_id": item.evidence_id,
                    "chunk_id": item.chunk_id,
                    "source_type": _enum_value(item.source_type),
                    "product_id": item.product_id,
                    "event_time": item.event_time,
                    "snippet": item.chunk_text,
                    "similarity_score": item.similarity_score,
                    "final_score": item.final_score,
                    "stale": item.is_stale,
                }
                for item in result.retrieved_chunks
            ],
            "evidence_ids": result.evidence_ids,
            "retrieval_confidence": result.retrieval_confidence,
            "evidence": [{"evidence_id": evidence_id, "source_table": "rag_memory_chunks"} for evidence_id in result.evidence_ids],
        }, list(result.missing_data_notes)

    def get_business_source(self, *, seller_id: UUID, spec: SourceToolSpec, filters: dict[str, Any], limit: int, offset: int) -> tuple[dict[str, Any], list[str]]:
        statement = select(spec.model)
        statement = self._scope_source_statement(statement, spec=spec, seller_id=seller_id)
        statement = self._filter_source_statement(statement, spec=spec, filters=filters, seller_id=seller_id)
        order_column = _model_column(spec.model, spec.date_field) if spec.date_field else _model_column(spec.model, "created_at")
        if order_column is not None:
            statement = statement.order_by(order_column.desc().nullslast())
        rows = self._db.execute(statement.limit(limit).offset(offset)).scalars().all()
        latest = self._latest_source_time(spec=spec, seller_id=seller_id, filters=filters)
        payload_rows = [_source_row_payload(row, spec=spec) for row in rows]
        missing = _missing_if_empty(payload_rows, f"No {spec.source_table} records were found for the requested seller scope.")
        missing.extend(_source_missing_notes(spec=spec, filters=filters))
        return {
            "source_table": spec.source_table,
            "rows": payload_rows,
            "pagination": {"limit": limit, "offset": offset, "has_next": len(payload_rows) == limit},
            "filters_used": _clean_filter_payload(filters),
            "freshness": {"latest_record_at": _scalar_iso(latest), "date_field": spec.date_field},
            "evidence": [_evidence(spec.source_table, getattr(row, "id", "unknown")) for row in rows[:20]],
        }, missing

    def _scope_source_statement(self, statement, *, spec: SourceToolSpec, seller_id: UUID):
        if spec.join_competitor_for_seller:
            return statement.join(Competitor, Competitor.id == spec.model.competitor_id).join(Product, Product.id == Competitor.product_id).where(Product.seller_id == seller_id)
        if spec.join_product_for_seller:
            return statement.join(Product, Product.id == spec.model.product_id).where(Product.seller_id == seller_id)
        seller_column = _model_column(spec.model, spec.seller_field)
        if seller_column is not None:
            return statement.where(seller_column == seller_id)
        product_column = _model_column(spec.model, spec.product_field)
        if product_column is not None:
            return statement.join(Product, Product.id == product_column).where(Product.seller_id == seller_id)
        raise ToolArgumentError(f"{spec.name} cannot be seller-scoped safely.")

    def _filter_source_statement(self, statement, *, spec: SourceToolSpec, filters: dict[str, Any], seller_id: UUID):
        product_id = filters.get("product_id")
        if product_id is not None and spec.product_field:
            product_column = _model_column(spec.model, spec.product_field)
            if product_column is not None:
                statement = statement.where(product_column == product_id)
        competitor_id = filters.get("competitor_id")
        if competitor_id is not None and spec.competitor_field:
            competitor_column = _model_column(spec.model, spec.competitor_field)
            if competitor_column is not None:
                statement = statement.where(competitor_column == competitor_id)
        date_column = _model_column(spec.model, spec.date_field)
        if date_column is not None:
            if filters.get("from_date") is not None:
                statement = statement.where(date_column >= _source_date_bound(date_column, filters["from_date"], end=False))
            if filters.get("to_date") is not None:
                statement = statement.where(date_column <= _source_date_bound(date_column, filters["to_date"], end=True))
        for filter_name, column_name in (("marketplace", "marketplace"), ("risk_level", "risk_level"), ("event_type", "event_type"), ("status", "status")):
            value = filters.get(filter_name)
            column = _model_column(spec.model, column_name)
            if value is not None and column is not None:
                statement = statement.where(column == value)
        category = filters.get("category")
        if category and (spec.join_product_for_seller or _model_column(spec.model, spec.product_field) is not None):
            product_column = _model_column(spec.model, spec.product_field)
            if product_column is not None and not spec.join_product_for_seller and not spec.join_competitor_for_seller:
                statement = statement.join(Product, Product.id == product_column)
            statement = statement.where(Product.seller_id == seller_id, Product.category == category)
        if spec.name == "get_products_missing_pricing_setup":
            fee_ids = self._product_ids_with_fee_policy(seller_id=seller_id, product_ids=[row[0] for row in self._db.execute(select(Product.id).where(Product.seller_id == seller_id)).all()])
            pricing_ids = self._product_ids_with_pricing_policy(seller_id=seller_id, product_ids=[row[0] for row in self._db.execute(select(Product.id).where(Product.seller_id == seller_id)).all()])
            all_ids = {row[0] for row in self._db.execute(select(Product.id).where(Product.seller_id == seller_id)).all()}
            statement = statement.where(Product.id.in_(list(all_ids - (set(fee_ids) & set(pricing_ids)))))
        if spec.name == "get_unresolved_alerts":
            statement = statement.where(Alert.delivery_status != AlertDeliveryStatus.delivered)
        if spec.name == "get_ignored_recommendations":
            status_column = _model_column(spec.model, "recommendation_status")
            if status_column is not None:
                statement = statement.where(status_column.in_(["DISMISSED", "IGNORED", "REJECTED"]))
        if spec.name == "get_pending_recommendations":
            status_column = _model_column(spec.model, "recommendation_status")
            if status_column is not None:
                statement = statement.where(status_column.in_(["OPEN", "PENDING"]))
        if spec.model in {RagMemoryChunk, RagMemoryDocument}:
            deleted_column = _model_column(spec.model, "deleted_at")
            if deleted_column is not None:
                statement = statement.where(deleted_column.is_(None))
            query = filters.get("query")
            if query:
                text_column = _first_model_column(spec.model, ("chunk_text", "summary_text", "title"))
                if text_column is not None:
                    statement = statement.where(text_column.ilike(f"%{query}%"))
        return statement

    def _latest_source_time(self, *, spec: SourceToolSpec, seller_id: UUID, filters: dict[str, Any]):
        date_column = _model_column(spec.model, spec.date_field)
        if date_column is None:
            return None
        statement = select(func.max(date_column))
        statement = self._scope_source_statement(statement, spec=spec, seller_id=seller_id)
        statement = self._filter_source_statement(statement, spec=spec, filters={**filters, "from_date": None, "to_date": None}, seller_id=seller_id)
        return self._db.execute(statement).scalar_one_or_none()

    def _sales_total(self, *, seller_id: UUID, product_id: UUID | None, from_date: date, to_date: date) -> Decimal:
        statement = select(func.coalesce(func.sum((SalesRecord.quantity_sold - SalesRecord.returned_units) * Product.selling_price), 0)).join(Product, Product.id == SalesRecord.product_id).where(
            SalesRecord.seller_id == seller_id,
            Product.seller_id == seller_id,
            SalesRecord.status.in_([SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED]),
            SalesRecord.is_test_order.is_(False),
            SalesRecord.sold_at >= _start_of_day(from_date),
            SalesRecord.sold_at <= _end_of_day(to_date),
        )
        if product_id:
            statement = statement.where(SalesRecord.product_id == product_id)
        return Decimal(self._db.execute(statement).scalar_one() or 0)

    def _revenue_factors(self, *, seller_id: UUID, product_id: UUID | None, from_date: date, to_date: date) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        factors: list[dict[str, Any]] = []
        evidence: dict[str, list[dict[str, Any]]] = {}
        risks, _ = self.get_inventory_risks(seller_id=seller_id, product_id=product_id, risk_level=None, limit=5)
        threats, _ = self.get_competitor_threats(seller_id=seller_id, product_id=product_id, from_date=from_date, to_date=to_date, limit=5)
        pricing, _ = self.get_pricing_recommendations(seller_id=seller_id, product_id=product_id, limit=5)
        for name, rows in (("inventory", risks), ("competitors", threats), ("pricing", pricing)):
            if rows:
                factors.append({"source": name, "reason": f"{len(rows)} relevant {name} signals found."})
                evidence[name] = [row.get("evidence") for row in rows if row.get("evidence")]
        return factors, evidence

    def _latest_ranking(self, *, seller_id: UUID, competitor_id: UUID, product_id: UUID):
        return self._db.execute(
            select(CompetitorRanking)
            .where(CompetitorRanking.seller_id == seller_id, CompetitorRanking.competitor_id == competitor_id, CompetitorRanking.product_id == product_id)
            .order_by(CompetitorRanking.calculated_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _product_statement(self, *, seller_id: UUID, filters: dict[str, Any]):
        statement = select(Product).where(Product.seller_id == seller_id)
        if filters.get("product_id"):
            statement = statement.where(Product.id == filters["product_id"])
        category = filters.get("category")
        if category:
            statement = statement.where(Product.category == category)
        if filters.get("status"):
            try:
                statement = statement.where(Product.status == ProductStatus(str(filters["status"]).upper()))
            except ValueError as exc:
                raise ToolArgumentError("Unsupported product status filter.") from exc
        if filters.get("listed"):
            statement = statement.where(self._active_listing_exists(Product.id, seller_id=seller_id))
        if filters.get("marketplace"):
            statement = statement.where(self._listing_exists(Product.id, seller_id=seller_id, marketplace=filters["marketplace"]))
        if filters.get("has_stock") is True:
            statement = statement.where(Product.stock_quantity > 0)
        if filters.get("has_stock") is False:
            statement = statement.where(Product.stock_quantity <= 0)
        if filters.get("missing_cost") is True:
            statement = statement.where(Product.cost_price.is_(None))
        if filters.get("missing_cost") is False:
            statement = statement.where(Product.cost_price.is_not(None))
        if filters.get("missing_selling_price") is True:
            statement = statement.where(Product.selling_price.is_(None))
        if filters.get("missing_fee_policy") is True:
            statement = statement.where(~self._fee_policy_exists(Product.id, seller_id=seller_id, category_column=Product.category))
        if filters.get("missing_fee_policy") is False:
            statement = statement.where(self._fee_policy_exists(Product.id, seller_id=seller_id, category_column=Product.category))
        if filters.get("missing_pricing_policy") is True:
            statement = statement.where(~self._pricing_policy_exists(Product.id, seller_id=seller_id))
        if filters.get("missing_pricing_policy") is False:
            statement = statement.where(self._pricing_policy_exists(Product.id, seller_id=seller_id))
        if filters.get("missing_sales") is True:
            statement = statement.where(~self._sales_exists(Product.id, seller_id=seller_id))
        if filters.get("missing_sales") is False:
            statement = statement.where(self._sales_exists(Product.id, seller_id=seller_id))
        return statement

    def _product_count(self, *, seller_id: UUID, filters: dict[str, Any]) -> int:
        statement = self._product_statement(seller_id=seller_id, filters=filters)
        return int(self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one() or 0)

    def _count_rows(self, statement) -> int:
        return int(self._db.execute(statement).scalar_one() or 0)

    def _table_exists(self, table_name: str) -> bool:
        return inspect(self._db.connection()).has_table(table_name)

    def _scoped_product_ids(self, *, seller_id: UUID, product_id: UUID | None, category: str | None, marketplace: str | None) -> tuple[list[UUID], list[str]]:
        filters = {"category": category, "marketplace": marketplace}
        if product_id:
            filters["product_id"] = product_id
        rows = self._db.execute(self._product_statement(seller_id=seller_id, filters=filters).with_only_columns(Product.id)).all()
        product_ids = [row[0] for row in rows]
        missing = self._unsupported_filter_notes(filters, seller_id=seller_id, product_ids=product_ids)
        return product_ids, missing

    def _filter_by_product_ids(self, statement, column, product_ids: list[UUID]):
        return statement.where(column.in_(product_ids))

    def _sync_action_center_items(self, *, seller_id: UUID) -> None:
        existing = {
            (row.source_type, row.source_id)
            for row in self._db.execute(select(ActionCenterItem.source_type, ActionCenterItem.source_id).where(ActionCenterItem.seller_id == seller_id)).all()
        }
        new_items: list[ActionCenterItem] = []
        reorder_rows = self._db.execute(select(ReorderRecommendation).options(joinedload(ReorderRecommendation.product)).where(
            ReorderRecommendation.seller_id == seller_id,
            ReorderRecommendation.recommendation_status == ReorderRecommendationStatus.OPEN,
            ReorderRecommendation.action == ReorderRecommendationAction.REORDER,
            ReorderRecommendation.recommended_quantity > 0,
        ).limit(100)).scalars().all()
        for row in reorder_rows:
            key = ("reorder_recommendations", str(row.id))
            if key in existing:
                continue
            new_items.append(
                ActionCenterItem(
                    seller_id=seller_id,
                    product_id=row.product_id,
                    source_domain="INVENTORY",
                    source_type=key[0],
                    source_id=key[1],
                    action_type="REORDER",
                    title=f"Reorder {row.product.title if row.product else 'product'}",
                    description=row.explanation,
                    priority=ActionCenterPriority(_risk_from_reorder(row)),
                    confidence=str(row.confidence_score),
                    expected_impact_json={"recommended_quantity": row.recommended_quantity, "deadline": row.reorder_deadline.isoformat() if row.reorder_deadline else None},
                    evidence_json=row.evidence,
                    due_at=datetime.combine(row.reorder_deadline, time.min, tzinfo=timezone.utc) if row.reorder_deadline else None,
                )
            )
        pricing_rows = []
        if self._table_exists("dynamic_pricing_recommendations"):
            pricing_rows = self._db.execute(select(DynamicPricingRecommendation).options(joinedload(DynamicPricingRecommendation.product)).where(DynamicPricingRecommendation.seller_id == seller_id, DynamicPricingRecommendation.recommendation_status == DynamicPricingRecommendationStatus.OPEN).limit(100)).scalars().all()
        for row in pricing_rows:
            key = ("dynamic_pricing_recommendations", str(row.id))
            if key in existing:
                continue
            new_items.append(
                ActionCenterItem(
                    seller_id=seller_id,
                    product_id=row.product_id,
                    source_domain="PRICING",
                    source_type=key[0],
                    source_id=key[1],
                    action_type=_enum_value(row.action) or "PRICE_REVIEW",
                    title=f"Review price for {row.product.title if row.product else 'product'}",
                    description=f"Recommended price: {row.recommended_price}",
                    priority=ActionCenterPriority.MEDIUM,
                    confidence=str(row.confidence_score),
                    expected_impact_json={"revenue_impact": str(row.revenue_impact) if row.revenue_impact is not None else None, "profit_impact": str(row.profit_impact) if row.profit_impact is not None else None},
                    evidence_json=row.evidence,
                    due_at=row.expires_at,
                )
            )
        alert_rows = []
        if self._table_exists("alerts"):
            alert_rows = self._db.execute(select(Alert).options(joinedload(Alert.product)).where(Alert.seller_id == seller_id, Alert.read_at.is_(None)).limit(100)).scalars().all()
        for row in alert_rows:
            key = ("alerts", str(row.id))
            if key in existing:
                continue
            new_items.append(
                ActionCenterItem(
                    seller_id=seller_id,
                    product_id=row.product_id,
                    source_domain="ALERTS",
                    source_type=key[0],
                    source_id=key[1],
                    action_type=_enum_value(row.action_type) or "REVIEW_ALERT",
                    title=f"{_enum_value(row.urgency_level)} alert for {row.product.title if row.product else 'product'}",
                    description=row.alert_type,
                    priority=ActionCenterPriority(_enum_value(row.urgency_level)),
                    confidence=_enum_value(row.confidence),
                    expected_impact_json={},
                    evidence_json={"alert_payload": row.payload or {}},
                )
            )
        if new_items:
            self._db.add_all(new_items)
            self._db.flush()

    def _sort_products(self, statement, sort_by: str | None):
        sort = sort_by or "created_at_desc"
        if sort == "created_at_asc":
            return statement.order_by(Product.created_at.asc(), Product.id.asc())
        if sort == "title_asc":
            return statement.order_by(Product.title.asc(), Product.id.asc())
        if sort == "title_desc":
            return statement.order_by(Product.title.desc(), Product.id.desc())
        if sort == "stock_desc":
            return statement.order_by(Product.stock_quantity.desc(), Product.id.desc())
        if sort == "stock_asc":
            return statement.order_by(Product.stock_quantity.asc(), Product.id.asc())
        if sort == "price_desc":
            return statement.order_by(Product.selling_price.desc(), Product.id.desc())
        if sort == "price_asc":
            return statement.order_by(Product.selling_price.asc(), Product.id.asc())
        return statement.order_by(Product.created_at.desc(), Product.id.desc())

    def _fee_policy_exists(self, product_id_column, *, seller_id: UUID, category_column=None):
        predicate = MarketplaceFeePolicy.seller_id == seller_id
        predicate = predicate & MarketplaceFeePolicy.is_active.is_(True)
        predicate = predicate & (
            (MarketplaceFeePolicy.product_id == product_id_column)
            | ((MarketplaceFeePolicy.product_id.is_(None)) & (MarketplaceFeePolicy.category == category_column))
            | ((MarketplaceFeePolicy.product_id.is_(None)) & (MarketplaceFeePolicy.category.is_(None)))
        )
        return select(MarketplaceFeePolicy.id).where(predicate).exists()

    def _pricing_policy_exists(self, product_id_column, *, seller_id: UUID):
        return (
            select(PricingPolicy.id)
            .where(
                PricingPolicy.seller_id == seller_id,
                PricingPolicy.product_id == product_id_column,
                PricingPolicy.is_active.is_(True),
            )
            .exists()
        )

    def _sales_exists(self, product_id_column, *, seller_id: UUID):
        return (
            select(SalesRecord.id)
            .where(
                SalesRecord.seller_id == seller_id,
                SalesRecord.product_id == product_id_column,
                SalesRecord.status.in_([SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED]),
                SalesRecord.is_test_order.is_(False),
            )
            .exists()
        )

    def _product_ids_with_fee_policy(self, *, seller_id: UUID, product_ids: list[UUID]) -> set[UUID]:
        if not product_ids:
            return set()
        products = self._db.execute(select(Product.id, Product.category).where(Product.seller_id == seller_id, Product.id.in_(product_ids))).all()
        direct = {
            row[0]
            for row in self._db.execute(
                select(MarketplaceFeePolicy.product_id).where(
                    MarketplaceFeePolicy.seller_id == seller_id,
                    MarketplaceFeePolicy.product_id.in_(product_ids),
                    MarketplaceFeePolicy.is_active.is_(True),
                )
            ).all()
            if row[0] is not None
        }
        categories = {
            row[0]
            for row in self._db.execute(
                select(MarketplaceFeePolicy.category).where(
                    MarketplaceFeePolicy.seller_id == seller_id,
                    MarketplaceFeePolicy.product_id.is_(None),
                    MarketplaceFeePolicy.is_active.is_(True),
                )
            ).all()
        }
        global_policy = None in categories
        return {product_id for product_id, category in products if global_policy or product_id in direct or category in categories}

    def _product_ids_with_pricing_policy(self, *, seller_id: UUID, product_ids: list[UUID]) -> set[UUID]:
        if not product_ids:
            return set()
        return {
            row[0]
            for row in self._db.execute(
                select(PricingPolicy.product_id).where(
                    PricingPolicy.seller_id == seller_id,
                    PricingPolicy.product_id.in_(product_ids),
                    PricingPolicy.is_active.is_(True),
                )
            ).all()
        }

    def _product_ids_with_sales(self, *, seller_id: UUID, product_ids: list[UUID]) -> set[UUID]:
        if not product_ids:
            return set()
        return {
            row[0]
            for row in self._db.execute(
                select(SalesRecord.product_id).where(
                    SalesRecord.seller_id == seller_id,
                    SalesRecord.product_id.in_(product_ids),
                    SalesRecord.status.in_([SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED]),
                    SalesRecord.is_test_order.is_(False),
                )
            ).all()
        }

    def _product_ids_with_visibility(self, *, seller_id: UUID, product_ids: list[UUID]) -> set[UUID]:
        if not product_ids:
            return set()
        return {row[0] for row in self._db.execute(select(ProductVisibilityMetric.product_id).where(ProductVisibilityMetric.seller_id == seller_id, ProductVisibilityMetric.product_id.in_(product_ids))).all()}

    def _product_ids_with_inventory_age(self, *, seller_id: UUID, product_ids: list[UUID]) -> set[UUID]:
        if not product_ids:
            return set()
        return {row[0] for row in self._db.execute(select(InventoryAgingSnapshot.product_id).where(InventoryAgingSnapshot.seller_id == seller_id, InventoryAgingSnapshot.product_id.in_(product_ids))).all()}

    def _has_fee_policy(self, *, seller_id: UUID, product_id: UUID, category: str | None) -> bool:
        return product_id in self._product_ids_with_fee_policy(seller_id=seller_id, product_ids=[product_id])

    def _has_pricing_policy(self, *, seller_id: UUID, product_id: UUID) -> bool:
        return product_id in self._product_ids_with_pricing_policy(seller_id=seller_id, product_ids=[product_id])

    def _latest_row(self, model, *, seller_id: UUID, product_id: UUID, order_column):
        return self._db.execute(
            select(model)
            .where(model.seller_id == seller_id, model.product_id == product_id)
            .order_by(order_column.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _revenue_total(self, *, seller_id: UUID, product_id: UUID | None, from_date: date | None, to_date: date | None) -> Decimal:
        resolved_from = from_date or date(1970, 1, 1)
        resolved_to = to_date or date.today()
        payload, _ = SalesRevenueAnalyticsService(self._db).get_revenue_summary(
            seller_id=seller_id,
            product_id=product_id,
            from_date=resolved_from,
            to_date=resolved_to,
            compare_to_previous_period=False,
        )
        return Decimal(payload.get("gross_revenue") or 0)

    def _estimated_profit_total(self, *, seller_id: UUID, from_date: date | None, to_date: date | None) -> Decimal | None:
        from_dt = _start_of_day(from_date or date(1970, 1, 1))
        to_dt = _end_of_day(to_date or date.today())
        value = self._db.execute(
            select(func.coalesce(func.sum((SalesRecord.quantity_sold - SalesRecord.returned_units) * (Product.selling_price - Product.cost_price)), 0))
            .join(Product, Product.id == SalesRecord.product_id)
            .where(
                SalesRecord.seller_id == seller_id,
                Product.seller_id == seller_id,
                SalesRecord.status.in_([SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED]),
                SalesRecord.is_test_order.is_(False),
                SalesRecord.sold_at >= from_dt,
                SalesRecord.sold_at <= to_dt,
            )
        ).scalar_one()
        return Decimal(value or 0)

    def _pending_recommendation_count(self, *, seller_id: UUID) -> int:
        total = self._count_rows(select(func.count()).select_from(Recommendation).join(Product, Recommendation.product_id == Product.id).where(Product.seller_id == seller_id))
        total += self._count_rows(select(func.count()).select_from(ReorderRecommendation).where(ReorderRecommendation.seller_id == seller_id, ReorderRecommendation.recommendation_status == ReorderRecommendationStatus.OPEN))
        total += self._count_rows(select(func.count()).select_from(DynamicPricingRecommendation).where(DynamicPricingRecommendation.seller_id == seller_id, DynamicPricingRecommendation.recommendation_status == DynamicPricingRecommendationStatus.OPEN))
        total += self._count_rows(select(func.count()).select_from(DeadStockRecoveryRecommendation).where(DeadStockRecoveryRecommendation.seller_id == seller_id, DeadStockRecoveryRecommendation.recommendation_status == DeadStockRecoveryRecommendationStatus.OPEN))
        return total

    def _freshness_summary(self, *, seller_id: UUID) -> dict[str, Any]:
        return {
            "latest_product_created_at": _scalar_iso(self._db.execute(select(func.max(Product.created_at)).where(Product.seller_id == seller_id)).scalar_one_or_none()),
            "latest_sale_at": _scalar_iso(self._db.execute(select(func.max(SalesRecord.sold_at)).where(SalesRecord.seller_id == seller_id)).scalar_one_or_none()),
            "latest_inventory_risk_at": _scalar_iso(self._db.execute(select(func.max(InventoryRiskAssessment.assessed_at)).where(InventoryRiskAssessment.seller_id == seller_id)).scalar_one_or_none()),
            "latest_competitor_event_at": _scalar_iso(self._db.execute(select(func.max(CompetitorEvent.detected_at)).where(CompetitorEvent.seller_id == seller_id)).scalar_one_or_none()),
        }

    def _summary_payload(self, *, summary: dict[str, Any], evidence_tables: tuple[str, ...], freshness: list[dict[str, Any]], extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "summary": summary,
            "freshness": freshness,
            "evidence": [_evidence(table, "seller_scope") for table in evidence_tables],
        }
        if extra:
            payload.update(extra)
        return payload

    def _freshness_for_tables(self, seller_id: UUID, tables: tuple[str, ...]) -> list[dict[str, Any]]:
        mapping = {
            "products": ("updated_at", lambda: self._db.execute(select(func.max(Product.updated_at)).where(Product.seller_id == seller_id)).scalar_one_or_none()),
            "product_marketplace_listings": ("updated_at", lambda: self._db.execute(select(func.max(ProductMarketplaceListing.updated_at)).where(ProductMarketplaceListing.seller_id == seller_id)).scalar_one_or_none()),
            "marketplace_fee_policies": ("updated_at", lambda: self._db.execute(select(func.max(MarketplaceFeePolicy.updated_at)).where(MarketplaceFeePolicy.seller_id == seller_id)).scalar_one_or_none()),
            "pricing_policies": ("updated_at", lambda: self._db.execute(select(func.max(PricingPolicy.updated_at)).where(PricingPolicy.seller_id == seller_id)).scalar_one_or_none()),
            "inventory_history": ("captured_at", lambda: self._db.execute(select(func.max(InventoryHistory.captured_at)).where(InventoryHistory.seller_id == seller_id)).scalar_one_or_none()),
            "sales_velocity": ("calculated_at", lambda: self._db.execute(select(func.max(SalesVelocity.calculated_at)).where(SalesVelocity.seller_id == seller_id)).scalar_one_or_none()),
            "stockout_predictions": ("calculated_at", lambda: self._db.execute(select(func.max(StockoutPrediction.calculated_at)).where(StockoutPrediction.seller_id == seller_id)).scalar_one_or_none()),
            "inventory_aging_snapshots": ("calculated_at", lambda: self._db.execute(select(func.max(InventoryAgingSnapshot.calculated_at)).where(InventoryAgingSnapshot.seller_id == seller_id)).scalar_one_or_none()),
            "inventory_risk_assessments": ("assessed_at", lambda: self._db.execute(select(func.max(InventoryRiskAssessment.assessed_at)).where(InventoryRiskAssessment.seller_id == seller_id)).scalar_one_or_none()),
            "reorder_recommendations": ("generated_at", lambda: self._db.execute(select(func.max(ReorderRecommendation.generated_at)).where(ReorderRecommendation.seller_id == seller_id)).scalar_one_or_none()),
            "dead_stock_assessments": ("assessed_at", lambda: self._db.execute(select(func.max(DeadStockAssessment.assessed_at)).where(DeadStockAssessment.seller_id == seller_id)).scalar_one_or_none()),
            "dead_stock_capital_recovery_estimates": ("calculated_at", lambda: self._db.execute(select(func.max(DeadStockCapitalRecoveryEstimate.calculated_at)).where(DeadStockCapitalRecoveryEstimate.seller_id == seller_id)).scalar_one_or_none()),
            "dead_stock_recovery_recommendations": ("generated_at", lambda: self._db.execute(select(func.max(DeadStockRecoveryRecommendation.generated_at)).where(DeadStockRecoveryRecommendation.seller_id == seller_id)).scalar_one_or_none()),
            "competitors": ("created_at", lambda: self._db.execute(select(func.max(Competitor.created_at)).select_from(Competitor).join(Product, Product.id == Competitor.product_id).where(Product.seller_id == seller_id)).scalar_one_or_none()),
            "competitor_snapshots": ("captured_at", lambda: self._db.execute(select(func.max(CompetitorSnapshot.captured_at)).select_from(CompetitorSnapshot).join(Product, Product.id == CompetitorSnapshot.product_id).where(Product.seller_id == seller_id)).scalar_one_or_none()),
            "competitor_events": ("detected_at", lambda: self._db.execute(select(func.max(CompetitorEvent.detected_at)).where(CompetitorEvent.seller_id == seller_id)).scalar_one_or_none()),
            "market_opportunities": ("detected_at", lambda: self._db.execute(select(func.max(MarketOpportunity.detected_at)).where(MarketOpportunity.seller_id == seller_id)).scalar_one_or_none()),
            "scrape_runs": ("created_at", lambda: self._db.execute(select(func.max(ScrapeRun.created_at)).where(ScrapeRun.seller_id == seller_id)).scalar_one_or_none()),
            "dynamic_pricing_recommendations": ("generated_at", lambda: self._db.execute(select(func.max(DynamicPricingRecommendation.generated_at)).where(DynamicPricingRecommendation.seller_id == seller_id)).scalar_one_or_none()),
            "pricing_analytics_snapshots": ("calculated_at", lambda: self._db.execute(select(func.max(PricingAnalyticsSnapshot.calculated_at)).where(PricingAnalyticsSnapshot.seller_id == seller_id)).scalar_one_or_none()),
            "demand_elasticity_estimates": ("calculated_at", lambda: self._db.execute(select(func.max(DemandElasticityEstimate.calculated_at)).where(DemandElasticityEstimate.seller_id == seller_id)).scalar_one_or_none()),
            "product_price_history": ("changed_at", lambda: self._db.execute(select(func.max(ProductPriceHistory.changed_at)).where(ProductPriceHistory.seller_id == seller_id)).scalar_one_or_none()),
            "promotion_plans": ("updated_at", lambda: self._db.execute(select(func.max(PromotionPlan.updated_at)).where(PromotionPlan.seller_id == seller_id)).scalar_one_or_none()),
            "promotion_results": ("updated_at", lambda: self._db.execute(select(func.max(PromotionResult.updated_at)).where(PromotionResult.seller_id == seller_id)).scalar_one_or_none()),
            "product_visibility_metrics": ("metric_date", lambda: self._db.execute(select(func.max(ProductVisibilityMetric.metric_date)).where(ProductVisibilityMetric.seller_id == seller_id)).scalar_one_or_none()),
            "alerts": ("created_at", lambda: self._db.execute(select(func.max(Alert.created_at)).where(Alert.seller_id == seller_id)).scalar_one_or_none()),
            "recommendations": ("created_at", lambda: self._db.execute(select(func.max(Recommendation.created_at)).select_from(Recommendation).join(Product, Product.id == Recommendation.product_id).where(Product.seller_id == seller_id)).scalar_one_or_none()),
            "action_center_items": ("updated_at", lambda: self._db.execute(select(func.max(ActionCenterItem.updated_at)).where(ActionCenterItem.seller_id == seller_id)).scalar_one_or_none()),
        }
        output = []
        for table in tables:
            date_field, loader = mapping.get(table, (None, lambda: None))
            if not self._table_exists(table):
                output.append({"source_table": table, "date_field": date_field, "latest_record_at": None})
                continue
            output.append({"source_table": table, "date_field": date_field, "latest_record_at": _scalar_iso(loader())})
        return output

    def _memory_coverage_summary(self, *, seller_id: UUID) -> dict[str, Any]:
        total = self._count_rows(select(func.count()).select_from(RagMemoryDocument).where(RagMemoryDocument.seller_id == seller_id, RagMemoryDocument.deleted_at.is_(None)))
        embedded = self._count_rows(select(func.count()).select_from(RagMemoryDocument).where(RagMemoryDocument.seller_id == seller_id, RagMemoryDocument.deleted_at.is_(None), RagMemoryDocument.embedding_status == RagMemoryEmbeddingStatus.EMBEDDED))
        missing = [] if total and total == embedded else ["MEMORY_COVERAGE_INCOMPLETE"]
        return {"summary": {"indexed_documents": embedded, "total_documents": total, "coverage_complete": bool(total and total == embedded)}, "missing_data": missing}

    def _unsupported_filter_notes(self, filters: dict[str, Any], *, seller_id: UUID | None = None, product_ids: list[UUID] | None = None) -> list[str]:
        notes = []
        if filters.get("marketplace"):
            if seller_id is not None:
                notes.extend(self._missing_marketplace_notes(seller_id=seller_id, product_ids=product_ids))
        if filters.get("missing_sales"):
            notes.append("Sales completeness is not tracked; missing_sales means no completed/fulfilled sales records were found, not guaranteed zero sales.")
        return notes

    def _product_payload(self, product: Product, *, listings: list[ProductMarketplaceListing], has_fee_policy: bool, has_pricing_policy: bool, has_sales: bool) -> dict[str, Any]:
        return {
            **self._product_ref_with_setup(product, listings=listings),
            "has_fee_policy": has_fee_policy,
            "has_pricing_policy": has_pricing_policy,
            "has_sales_history": has_sales,
            "missing_setup_fields": self._missing_setup_for_product(product, has_fee_policy=has_fee_policy, has_pricing_policy=has_pricing_policy),
        }

    def _product_ref_with_setup(self, product: Product, *, listings: list[ProductMarketplaceListing] | None = None) -> dict[str, Any]:
        listing_rows = listings if listings is not None else []
        primary_listing = _primary_listing(listing_rows)
        return {
            "id": str(product.id),
            "title": product.title,
            "sku": product.sku,
            "category": product.category,
            "marketplace": primary_listing.marketplace if primary_listing else None,
            "status": _enum_value(product.status),
            "selling_price": primary_listing.selling_price if primary_listing and primary_listing.selling_price is not None else product.selling_price,
            "cost_price": product.cost_price,
            "currency": primary_listing.currency if primary_listing else None,
            "stock_quantity": product.stock_quantity,
            "created_at": product.created_at,
            "updated_at": product.updated_at,
            "marketplace_listings": [_listing_payload(listing) for listing in listing_rows],
            "evidence": _evidence("products", product.id),
        }

    def _missing_setup_for_product(self, product: Product, *, has_fee_policy: bool, has_pricing_policy: bool) -> list[str]:
        missing = []
        if product.cost_price is None:
            missing.append("COST")
        if product.selling_price is None:
            missing.append("SELLING_PRICE")
        if not has_fee_policy:
            missing.append("MARKETPLACE_FEE_POLICY")
        if not has_pricing_policy:
            missing.append("PRICING_POLICY")
        if product.sku is None:
            missing.append("SKU")
        return missing

    def _listing_exists(self, product_id_column, *, seller_id: UUID, marketplace: str):
        return (
            select(ProductMarketplaceListing.id)
            .where(
                ProductMarketplaceListing.seller_id == seller_id,
                ProductMarketplaceListing.product_id == product_id_column,
                ProductMarketplaceListing.marketplace == marketplace,
                ProductMarketplaceListing.archived_at.is_(None),
            )
            .exists()
        )

    def _active_listing_exists(self, product_id_column, *, seller_id: UUID):
        return (
            select(ProductMarketplaceListing.id)
            .where(
                ProductMarketplaceListing.seller_id == seller_id,
                ProductMarketplaceListing.product_id == product_id_column,
                ProductMarketplaceListing.listing_status == ProductMarketplaceListingStatus.ACTIVE,
                ProductMarketplaceListing.archived_at.is_(None),
            )
            .exists()
        )

    def _listings_for_product(self, *, seller_id: UUID, product_id: UUID) -> list[ProductMarketplaceListing]:
        return self._db.execute(
            select(ProductMarketplaceListing)
            .where(
                ProductMarketplaceListing.seller_id == seller_id,
                ProductMarketplaceListing.product_id == product_id,
                ProductMarketplaceListing.archived_at.is_(None),
            )
            .order_by(ProductMarketplaceListing.is_primary.desc(), ProductMarketplaceListing.created_at.desc())
        ).scalars().all()

    def _listings_by_product(self, *, seller_id: UUID, product_ids: list[UUID]) -> dict[UUID, list[ProductMarketplaceListing]]:
        if not product_ids:
            return {}
        rows = self._db.execute(
            select(ProductMarketplaceListing)
            .where(
                ProductMarketplaceListing.seller_id == seller_id,
                ProductMarketplaceListing.product_id.in_(product_ids),
                ProductMarketplaceListing.archived_at.is_(None),
            )
            .order_by(ProductMarketplaceListing.is_primary.desc(), ProductMarketplaceListing.created_at.desc())
        ).scalars().all()
        grouped: dict[UUID, list[ProductMarketplaceListing]] = {}
        for row in rows:
            grouped.setdefault(row.product_id, []).append(row)
        return grouped

    def _missing_marketplace_notes(self, *, seller_id: UUID, product_ids: list[UUID] | None) -> list[str]:
        statement = select(func.count()).select_from(Product).where(Product.seller_id == seller_id, ~self._listing_exists(Product.id, seller_id=seller_id, marketplace="%"))
        if product_ids is not None:
            if not product_ids:
                return []
            statement = select(func.count()).select_from(Product).where(
                Product.seller_id == seller_id,
                Product.id.in_(product_ids),
                ~select(ProductMarketplaceListing.id)
                .where(
                    ProductMarketplaceListing.seller_id == seller_id,
                    ProductMarketplaceListing.product_id == Product.id,
                    ProductMarketplaceListing.archived_at.is_(None),
                )
                .exists(),
            )
        else:
            statement = select(func.count()).select_from(Product).where(
                Product.seller_id == seller_id,
                ~select(ProductMarketplaceListing.id)
                .where(
                    ProductMarketplaceListing.seller_id == seller_id,
                    ProductMarketplaceListing.product_id == Product.id,
                    ProductMarketplaceListing.archived_at.is_(None),
                )
                .exists(),
            )
        missing_count = int(self._db.execute(statement).scalar_one() or 0)
        if missing_count:
            return ["MISSING_MARKETPLACE: Marketplace listing setup is missing for one or more products; no fake marketplace was returned."]
        return []


def _limit_product_query(statement, product_id: UUID | None, column):
    return statement.where(column == product_id) if product_id else statement


def _product_filters(args: dict[str, Any]) -> dict[str, Any]:
    status = args.get("status")
    listed_filter = status in {"LISTED", "PUBLISHED"}
    return {
        "status": None if listed_filter else status,
        "category": args.get("category"),
        "marketplace": args.get("marketplace"),
        "has_stock": args.get("has_stock"),
        "missing_cost": args.get("missing_cost"),
        "missing_selling_price": args.get("missing_selling_price"),
        "missing_fee_policy": args.get("missing_fee_policy"),
        "missing_pricing_policy": args.get("missing_pricing_policy"),
        "missing_sales": args.get("missing_sales"),
        "listed": listed_filter or None,
    }


def _clean_filter_payload(filters: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_safe(value) for key, value in filters.items() if value is not None}


def _product_ref(product) -> dict[str, Any] | None:
    if product is None:
        return None
    return {"id": str(product.id), "title": product.title, "category": product.category}


def _primary_listing(listings: list[ProductMarketplaceListing]) -> ProductMarketplaceListing | None:
    if not listings:
        return None
    return next((listing for listing in listings if listing.is_primary), listings[0])


def _listing_payload(listing: ProductMarketplaceListing) -> dict[str, Any]:
    return {
        "id": str(listing.id),
        "marketplace": listing.marketplace,
        "marketplace_listing_id": listing.marketplace_listing_id,
        "listing_url": listing.listing_url,
        "listing_status": _enum_value(listing.listing_status),
        "currency": listing.currency,
        "selling_price": listing.selling_price,
        "previous_selling_price": listing.previous_selling_price,
        "category_on_marketplace": listing.category_on_marketplace,
        "title_on_marketplace": listing.title_on_marketplace,
        "is_primary": listing.is_primary,
        "published_at": listing.published_at,
        "last_synced_at": listing.last_synced_at,
        "updated_at": listing.updated_at,
    }


def _competitor_ref(competitor) -> dict[str, Any] | None:
    if competitor is None:
        return None
    return {"id": str(competitor.id), "title": competitor.competitor_title, "store": competitor.competitor_store, "marketplace": competitor.marketplace}


def _stockout_payload(stockout) -> dict[str, Any] | None:
    if stockout is None:
        return None
    return {
        "status": _enum_value(stockout.prediction_status),
        "days_remaining": stockout.days_remaining,
        "predicted_stockout_date": stockout.predicted_stockout_date,
        "confidence": stockout.confidence_score,
    }


def _evidence(source_table: str, source_id: Any, payload: Any = None) -> dict[str, Any]:
    return {"source_table": source_table, "source_id": str(source_id), "payload": payload or {}}


RESTRICTED_FIELD_FRAGMENTS = ("password", "token", "api_key", "apikey", "cookie", "secret", "stack", "raw_html", "html", "telegram_chat_id", "celery_task_id", "error_message", "delivery_error")


def _model_column(model: Any, name: str | None):
    if not name:
        return None
    return getattr(model, name, None)


def _first_model_column(model: Any, names: tuple[str, ...]):
    for name in names:
        column = _model_column(model, name)
        if column is not None:
            return column
    return None


def _source_date_bound(column: Any, value: date, *, end: bool) -> date | datetime:
    try:
        python_type = column.type.python_type
    except (AttributeError, NotImplementedError):
        python_type = datetime
    return value if python_type is date else (_end_of_day(value) if end else _start_of_day(value))


def _source_row_payload(row: Any, *, spec: SourceToolSpec) -> dict[str, Any]:
    allowed = set(spec.safe_fields)
    payload: dict[str, Any] = {}
    for column in row.__table__.columns:
        name = column.name
        if allowed and name not in allowed:
            continue
        if _field_is_restricted(name):
            continue
        payload[name] = _json_safe(getattr(row, name, None))
    product = getattr(row, "product", None)
    competitor = getattr(row, "competitor", None)
    if product is not None:
        payload["product"] = _product_ref(product)
    if competitor is not None:
        payload["competitor"] = _competitor_ref(competitor)
    payload["evidence"] = _evidence(spec.source_table, getattr(row, "id", "unknown"))
    return payload


def _promotion_plan_payload(row: PromotionPlan) -> dict[str, Any]:
    return {
        "id": row.id,
        "product": _product_ref(row.product),
        "category": row.category,
        "marketplace": row.marketplace,
        "promotion_type": row.promotion_type,
        "title": row.title,
        "description": row.description,
        "proposed_discount_rate": row.proposed_discount_rate,
        "proposed_price": row.proposed_price,
        "planned_start_at": row.planned_start_at,
        "planned_end_at": row.planned_end_at,
        "status": _enum_value(row.status),
        "source": row.source,
        "safety_checks": row.safety_checks_json or {},
        "expected_impact": row.expected_impact_json or {},
        "marketplace_execution_enabled": False,
        "evidence": _evidence("promotion_plans", row.id),
    }


def _promotion_result_payload(row: PromotionResult) -> dict[str, Any]:
    return {
        "id": row.id,
        "promotion_plan_id": row.promotion_plan_id,
        "product": _product_ref(row.product),
        "marketplace": row.marketplace,
        "started_at": row.started_at,
        "ended_at": row.ended_at,
        "units_sold": row.units_sold,
        "gross_revenue": row.gross_revenue,
        "estimated_profit": row.estimated_profit,
        "spend": row.spend,
        "discount_cost": row.discount_cost,
        "roi": row.roi,
        "result_status": _enum_value(row.result_status),
        "missing_data": row.missing_data_json or {},
        "evidence": _evidence("promotion_results", row.id, row.evidence_json),
    }


def _product_price_history_payload(row: ProductPriceHistory) -> dict[str, Any]:
    return {
        "id": row.id,
        "product": _product_ref(row.product),
        "listing_id": row.listing_id,
        "marketplace": row.marketplace,
        "old_price": row.old_price,
        "new_price": row.new_price,
        "currency": row.currency,
        "reason": row.reason,
        "source": _enum_value(row.source),
        "baseline_not_historical_change": _enum_value(row.source) == "BASELINE_CURRENT_PRICE",
        "changed_at": row.changed_at,
        "changed_by_user_id": row.changed_by_user_id,
        "evidence": _evidence("product_price_history", row.id),
    }


def _field_is_restricted(name: str) -> bool:
    normalized = name.lower()
    return any(fragment in normalized for fragment in RESTRICTED_FIELD_FRAGMENTS)


def _source_missing_notes(*, spec: SourceToolSpec, filters: dict[str, Any]) -> list[str]:
    notes = []
    if filters.get("marketplace") and _model_column(spec.model, "marketplace") is None:
        notes.append(f"{spec.source_table} does not store marketplace directly; marketplace filter could not be applied.")
    if filters.get("category") and not (spec.product_field or spec.join_product_for_seller or spec.join_competitor_for_seller):
        notes.append(f"{spec.source_table} cannot be category-filtered without product linkage.")
    if spec.name in {"get_visibility_summary", "get_visibility_history", "get_listing_quality_issues"}:
        notes.append("Missing visibility records mean visibility is unavailable, not low visibility.")
    if spec.name in {"get_capital_recovery_estimates", "get_capital_recovery_summary"}:
        notes.append("Capital recovery values are returned only from persisted estimates; the tool does not estimate locked capital without stored cost evidence.")
    if spec.name in {"get_margin_safety", "simulate_price_change"}:
        notes.append("Margin safety fails closed when cost, fee, or policy data is missing.")
    return notes


def _spec_value(product: Product, key: str) -> str | None:
    specs = product.specifications or {}
    for candidate in (key, key.upper(), key.lower()):
        value = specs.get(candidate)
        if value:
            return str(value)
    return None


def _safe_ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator in (None, Decimal("0")):
        return None
    return numerator / denominator


def _scalar_iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _inventory_age_payload(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "as_of_date": row.as_of_date,
        "oldest_age_days": row.oldest_age_days,
        "newest_age_days": row.newest_age_days,
        "weighted_average_age_days": row.weighted_average_age_days,
        "age_source": _enum_value(row.age_source),
        "is_estimated": row.is_estimated,
        "confidence": row.confidence_score,
    }


def _last_sale_payload(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "sold_at": row.sold_at,
        "quantity_sold": row.quantity_sold,
        "returned_units": row.returned_units,
        "status": _enum_value(row.status),
        "evidence": _evidence("sales_records", row.id),
    }


def _sales_velocity_payload(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "daily_sales_rate": getattr(row, "daily_sales_rate", None),
        "data_status": _enum_value(getattr(row, "data_status", None)),
        "calculated_at": getattr(row, "calculated_at", None),
        "evidence": _evidence("sales_velocity", row.id),
    }


def _competitor_threat_payload(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "event_type": _enum_value(row.event_type),
        "severity": _enum_value(row.severity),
        "price_change_amount": row.price_change_amount,
        "price_change_percent": row.price_change_percent,
        "detected_at": row.detected_at,
        "evidence": _evidence("competitor_events", row.id),
    }


def _competitor_event_payload(row: CompetitorEvent) -> dict[str, Any]:
    return {
        "event_type": _enum_value(row.event_type),
        "severity": _enum_value(row.severity),
        "product": _product_ref(row.product),
        "competitor": _competitor_ref(row.competitor),
        "old_value": row.old_value,
        "new_value": row.new_value,
        "price_change_amount": row.price_change_amount,
        "price_change_percent": row.price_change_percent,
        "detected_at": row.detected_at,
        "evidence": _evidence("competitor_events", row.id),
    }


def _market_opportunity_payload(row: MarketOpportunity) -> dict[str, Any]:
    return {
        "product": _product_ref(row.product),
        "competitor": _competitor_ref(row.competitor),
        "opportunity_type": _enum_value(row.opportunity_type),
        "level": _enum_value(row.opportunity_level),
        "score": row.opportunity_score,
        "estimated_revenue": row.estimated_revenue,
        "recommended_action": _enum_value(row.recommended_action),
        "confidence": row.confidence_score,
        "status": _enum_value(row.status),
        "detected_at": row.detected_at,
        "evidence": _evidence("market_opportunities", row.id, row.evidence),
    }


def _pricing_payload(row) -> dict[str, Any] | None:
    if row is None:
        return None
    evidence = getattr(row, "evidence", None) or {}
    return {
        "action": _enum_value(row.action),
        "current_price": row.current_price,
        "recommended_price": evidence.get("recommended_target_price", row.recommended_price),
        "minimum_safe_price": row.minimum_safe_price,
        "expected_revenue": row.expected_revenue,
        "expected_profit": row.expected_profit,
        "confidence": row.confidence_score,
        "status": _enum_value(row.recommendation_status),
        "generated_at": row.generated_at,
        "evidence": _evidence("dynamic_pricing_recommendations", row.id),
    }


def _alert_action_payload(row: Alert) -> dict[str, Any]:
    return {
        "action_type": _enum_value(row.action_type),
        "product": _product_ref(row.product),
        "urgency": _enum_value(row.urgency_level),
        "confidence": _enum_value(row.confidence),
        "alert_type": row.alert_type,
        "delivery_status": _enum_value(row.delivery_status),
        "created_at": row.created_at,
        "evidence": _evidence("alerts", row.id),
    }


def _action_center_payload(row: ActionCenterItem) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "action_type": row.action_type,
        "title": row.title,
        "description": row.description,
        "product_id": str(row.product_id) if row.product_id else None,
        "source_domain": row.source_domain,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "urgency": _enum_value(row.priority),
        "priority": _enum_value(row.priority),
        "confidence": row.confidence,
        "expected_impact": row.expected_impact_json or {},
        "status": _enum_value(row.status),
        "due_at": row.due_at,
        "evidence": _evidence("action_center_items", row.id, row.evidence_json),
    }


def _inventory_risk_payload(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "risk_level": _enum_value(row.risk_level),
        "risk_score": row.risk_score,
        "confidence": row.confidence_score,
        "assessed_at": row.assessed_at,
        "evidence": _evidence("inventory_risk_assessments", row.id),
    }


def _dead_stock_payload(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "classification": _enum_value(row.classification),
        "risk_level": _enum_value(row.risk_level),
        "eligible_quantity": row.eligible_quantity,
        "inventory_age_days": row.inventory_age_days,
        "confidence": row.confidence_score,
        "assessed_at": row.assessed_at,
        "evidence": _evidence("dead_stock_assessments", row.id),
    }


def _visibility_payload(row) -> dict[str, Any] | None:
    if row is None:
        return None
    ctr = None
    if row.views:
        ctr = Decimal(row.clicks) / Decimal(row.views)
    return {
        "metric_date": row.metric_date,
        "impressions": row.impressions,
        "views": row.views,
        "clicks": row.clicks,
        "ctr": ctr,
        "search_rank": row.search_rank,
        "listing_quality_score": row.listing_quality_score,
        "evidence": _evidence("product_visibility_metrics", row.id),
    }


def _filters_for_setup_type(setup_type: str | None) -> set[str]:
    if not setup_type:
        return set()
    return {setup_type}


def _next_action_for_setup(field: str) -> str:
    return {
        "COST": "Add product cost or landed cost.",
        "SELLING_PRICE": "Add selling price.",
        "MARKETPLACE_FEE_POLICY": "Configure marketplace fee policy.",
        "PRICING_POLICY": "Configure pricing policy.",
        "INVENTORY_AGE_SOURCE": "Sync stock-in or inventory aging data.",
        "SALES_HISTORY": "Import or sync completed sales history.",
        "VISIBILITY_DATA": "Import listing visibility metrics.",
        "SKU": "Add SKU in product specifications if available.",
    }.get(field, "Review product setup.")


def _extract_evidence(data: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "source_table" in value and "source_id" in value:
                evidence.append(value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    return evidence


def _normalize_tool_payload(data: dict[str, Any], *, tool: ToolDefinition) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {"value": data}
    if data.get("missing_data") is None:
        data["missing_data"] = []
    if data.get("evidence") is None:
        data["evidence"] = []
    if data.get("freshness") is None:
        data["freshness"] = _freshness_from_payload(data, tool=tool)
    return data


def _freshness_from_payload(data: dict[str, Any], *, tool: ToolDefinition) -> list[dict[str, Any]]:
    latest = _latest_datetime(data)
    evidence = _extract_evidence(data)
    if latest is None:
        status = "MISSING" if not evidence else "UNKNOWN"
    else:
        compare = latest if latest.tzinfo else latest.replace(tzinfo=timezone.utc)
        status = "STALE" if (datetime.now(timezone.utc) - compare).days > 90 else "FRESH"
    return [
        {
            "domain": domain,
            "source_table": _first_source_table(data),
            "latest_available_at": latest.isoformat() if latest else None,
            "status": status,
            "message": f"{tool.name} freshness is {status.lower()}.",
        }
        for domain in (tool.catalog_domains or ("GENERAL_BUSINESS",))
    ]


def _first_source_table(value: Any) -> str | None:
    if isinstance(value, dict):
        if value.get("source_table"):
            return str(value["source_table"])
        for item in value.values():
            found = _first_source_table(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _first_source_table(item)
            if found:
                return found
    return None


def _latest_datetime(value: Any) -> datetime | None:
    values: list[datetime] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"event_time", "created_at", "updated_at", "captured_at", "calculated_at", "generated_at", "sold_at", "latest_available_at", "metric_date"}:
                parsed = _parse_datetime(item)
                if parsed:
                    values.append(parsed)
            else:
                parsed = _latest_datetime(item)
                if parsed:
                    values.append(parsed)
    elif isinstance(value, list):
        for item in value:
            parsed = _latest_datetime(item)
            if parsed:
                values.append(parsed)
    return max(values) if values else None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _missing_if_empty(rows: list[Any], message: str) -> list[str]:
    return [] if rows else [message]


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _sum_decimal(values) -> Decimal | None:
    present = [Decimal(value) for value in values if value is not None]
    if not present:
        return None
    return sum(present, Decimal("0"))


def _counts_by(rows: list[Any], attribute: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = _enum_value(getattr(row, attribute, None))
        if key is None:
            key = "UNKNOWN"
        key = str(key)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _policy_scope_counts(rows: list[Any]) -> dict[str, int]:
    counts = {"product": 0, "category": 0, "seller_default": 0}
    for row in rows:
        if getattr(row, "product_id", None) is not None:
            counts["product"] += 1
        elif getattr(row, "category", None) is not None:
            counts["category"] += 1
        else:
            counts["seller_default"] += 1
    return counts


def _risk_from_reorder(row: ReorderRecommendation) -> str:
    if row.reorder_deadline and row.reorder_deadline <= date.today():
        return "CRITICAL"
    if row.action == "REORDER" or _enum_value(row.action) == "REORDER":
        return "HIGH"
    return "LOW"


def _urgency_rank(value: Any) -> int:
    return {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(str(value or "").upper(), 0)


def _start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _end_of_day(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _date_filter(statement, column, from_date: date | None, to_date: date | None):
    if from_date:
        statement = statement.where(column >= from_date if not isinstance(from_date, date) else column >= from_date)
    if to_date:
        statement = statement.where(column <= to_date if not isinstance(to_date, date) else column <= to_date)
    return statement


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    output = []
    for item in items:
        key = (item.get("source_table"), item.get("source_id"))
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _top_issues(product_setup: dict[str, Any], inventory: dict[str, Any], pricing: dict[str, Any], dead_stock: dict[str, Any], alerts: dict[str, Any], missing: list[str]) -> list[dict[str, Any]]:
    candidates = [
        ("MISSING_FEE_POLICY", product_setup.get("missing_setup_counts", {}).get("missing_fee_policy", 0), "Products missing marketplace fee policy."),
        ("MISSING_PRICING_POLICY", product_setup.get("missing_setup_counts", {}).get("missing_pricing_policy", 0), "Products missing pricing policy."),
        ("STOCKOUT_RISK", inventory.get("summary", {}).get("stockout_risk_count", 0), "High or critical stockout risks found."),
        ("DEAD_STOCK", dead_stock.get("summary", {}).get("dead_stock_product_count", 0), "Dead-stock products found."),
        ("UNRESOLVED_ALERTS", alerts.get("summary", {}).get("unresolved_alert_count", 0), "Unresolved alerts found."),
    ]
    issues = [{"code": code, "count": count, "message": message} for code, count, message in candidates if count]
    issues.extend({"code": item, "count": None, "message": item} for item in missing[:5])
    return sorted(issues, key=lambda item: item["count"] or 0, reverse=True)


def _next_actions_from_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapping = {
        "MISSING_FEE_POLICY": "Add marketplace fee policies for affected products.",
        "MISSING_PRICING_POLICY": "Create active pricing policies for products missing pricing setup.",
        "STOCKOUT_RISK": "Review reorder recommendations and supplier lead times.",
        "DEAD_STOCK": "Review dead-stock recovery recommendations.",
        "UNRESOLVED_ALERTS": "Resolve or acknowledge pending alerts.",
        "MEMORY_COVERAGE_INCOMPLETE": "Run RAG memory backfill/indexing for complete historical context.",
    }
    return [{"issue_code": item["code"], "action": mapping.get(item["code"], "Review missing data before acting.")} for item in issues]


def _seo_issue(metric: ProductVisibilityMetric) -> str:
    if metric.listing_quality_score is None:
        return "Listing quality score is unavailable."
    if metric.listing_quality_score < 60:
        return "Listing quality score is low."
    if metric.search_rank and metric.search_rank > 20:
        return "Search rank is weak."
    if metric.views and metric.clicks / max(metric.views, 1) < 0.02:
        return "Click-through rate is low."
    return "Monitor listing visibility."


def _seo_suggestion(metric: ProductVisibilityMetric) -> str:
    if metric.listing_quality_score is not None and metric.listing_quality_score < 60:
        return "Improve title, description, images, and key attributes."
    if metric.search_rank and metric.search_rank > 20:
        return "Refresh keywords and category alignment."
    return "Review visibility metrics before editing the listing."


def _validation_message(exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", []))
    message = first.get("msg", "Invalid arguments.")
    return f"{location}: {message}" if location else str(message)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
