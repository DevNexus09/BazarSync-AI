from __future__ import annotations

from datetime import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.scrape_run import ScrapeRun
    from app.models.product import Product
    from app.models.pricing_analytics_snapshot import PricingAnalyticsSnapshot
    from app.models.alert import Alert
    from app.models.demand_elasticity_estimate import DemandElasticityEstimate
    from app.models.dynamic_pricing_recommendation import DynamicPricingRecommendation
    from app.models.alert_delivery_log import AlertDeliveryLog
    from app.models.competitor_event import CompetitorEvent
    from app.models.competitor_ranking import CompetitorRanking
    from app.models.inventory_history import InventoryHistory
    from app.models.inventory_risk import InventoryRiskAssessment
    from app.models.market_opportunity import MarketOpportunity
    from app.models.sales_record import SalesRecord
    from app.models.sales_velocity import SalesVelocity
    from app.models.reorder_recommendation import ReorderRecommendation
    from app.models.stockout_prediction import StockoutPrediction
    from app.models.telegram_connection import SellerTelegramConnection
    from app.models.telegram_inventory_alert import TelegramInventoryAlert
    from app.models.telegram_snapshot_log import TelegramProductSnapshotLog


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
    sales_records: Mapped[list["SalesRecord"]] = relationship(
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
    demand_elasticity_estimates: Mapped[list["DemandElasticityEstimate"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    dynamic_pricing_recommendations: Mapped[list["DynamicPricingRecommendation"]] = relationship(
        back_populates="seller",
        cascade="all, delete-orphan",
    )
