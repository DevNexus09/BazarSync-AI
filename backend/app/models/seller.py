from __future__ import annotations

from datetime import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.action_center_item import ActionCenterItem
    from app.models.scrape_run import ScrapeRun
    from app.models.product import Product
    from app.models.product import ProductMarketplaceListing
    from app.models.pricing_analytics_snapshot import PricingAnalyticsSnapshot
    from app.models.product_price_history import ProductPriceHistory
    from app.models.promotion import PromotionPlan, PromotionResult
    from app.models.alert import Alert
    from app.models.demand_elasticity_estimate import DemandElasticityEstimate
    from app.models.dead_stock_assessment import DeadStockAssessment
    from app.models.dead_stock_capital_recovery import DeadStockCapitalRecoveryEstimate
    from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryRecommendation
    from app.models.dynamic_pricing_recommendation import DynamicPricingRecommendation
    from app.models.alert_delivery_log import AlertDeliveryLog
    from app.models.competitor_event import CompetitorEvent
    from app.models.competitor_ranking import CompetitorRanking
    from app.models.inventory_history import InventoryHistory
    from app.models.inventory_aging import InventoryAgingSnapshot
    from app.models.inventory_risk import InventoryRiskAssessment
    from app.models.market_opportunity import MarketOpportunity
    from app.models.sales_record import SalesRecord
    from app.models.sales_data_coverage import SalesDataCoverage
    from app.models.sales_velocity import SalesVelocity
    from app.models.reorder_recommendation import ReorderRecommendation
    from app.models.stockout_prediction import StockoutPrediction
    from app.models.telegram_connection import SellerTelegramConnection
    from app.models.telegram_inventory_alert import TelegramInventoryAlert
    from app.models.telegram_snapshot_log import TelegramProductSnapshotLog
    from app.models.rag_memory import RagMemoryChunk, RagMemoryDocument
    from app.models.rag_index_outbox import RagIndexOutbox
    from app.models.copilot import CopilotConversation
    from app.models.password_reset import PasswordResetAuthorization, PasswordResetChallenge
    from app.models.security_audit_event import SecurityAuditEvent


class Seller(Base):
    __tablename__ = "sellers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_line: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    products: Mapped[list["Product"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    product_marketplace_listings: Mapped[list["ProductMarketplaceListing"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
        overlaps="marketplace_listings,product",
    )
    scrape_runs: Mapped[list["ScrapeRun"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    competitor_events: Mapped[list["CompetitorEvent"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    competitor_rankings: Mapped[list["CompetitorRanking"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    market_opportunities: Mapped[list["MarketOpportunity"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    inventory_history: Mapped[list["InventoryHistory"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    inventory_aging_snapshots: Mapped[list["InventoryAgingSnapshot"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    dead_stock_assessments: Mapped[list["DeadStockAssessment"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    dead_stock_recovery_recommendations: Mapped[list["DeadStockRecoveryRecommendation"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    dead_stock_capital_recovery_estimates: Mapped[list["DeadStockCapitalRecoveryEstimate"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    sales_records: Mapped[list["SalesRecord"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    sales_data_coverage: Mapped[list["SalesDataCoverage"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    sales_velocity: Mapped[list["SalesVelocity"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    stockout_predictions: Mapped[list["StockoutPrediction"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    reorder_recommendations: Mapped[list["ReorderRecommendation"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    inventory_risk_assessments: Mapped[list["InventoryRiskAssessment"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    telegram_inventory_alerts: Mapped[list["TelegramInventoryAlert"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    alert_delivery_logs: Mapped[list["AlertDeliveryLog"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    snapshot_logs: Mapped[list["TelegramProductSnapshotLog"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    telegram_connection: Mapped["SellerTelegramConnection | None"] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
        uselist=False,
    )
    pricing_analytics_snapshots: Mapped[list["PricingAnalyticsSnapshot"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    product_price_history: Mapped[list["ProductPriceHistory"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    promotion_plans: Mapped[list["PromotionPlan"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    promotion_results: Mapped[list["PromotionResult"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    demand_elasticity_estimates: Mapped[list["DemandElasticityEstimate"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    dynamic_pricing_recommendations: Mapped[list["DynamicPricingRecommendation"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    rag_memory_documents: Mapped[list["RagMemoryDocument"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    rag_memory_chunks: Mapped[list["RagMemoryChunk"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    rag_index_outbox_events: Mapped[list["RagIndexOutbox"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    copilot_conversations: Mapped[list["CopilotConversation"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    action_center_items: Mapped[list["ActionCenterItem"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    password_reset_challenges: Mapped[list["PasswordResetChallenge"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    password_reset_authorizations: Mapped[list["PasswordResetAuthorization"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    security_audit_events: Mapped[list["SecurityAuditEvent"]] = relationship(
        back_populates="seller",
    )
