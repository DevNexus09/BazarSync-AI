from __future__ import annotations

from datetime import datetime
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.competitor import Competitor
    from app.models.competitor_event import CompetitorEvent
    from app.models.competitor_ranking import CompetitorRanking
    from app.models.market_opportunity import MarketOpportunity
    from app.models.competitor_snapshot import CompetitorSnapshot
    from app.models.inventory_history import InventoryHistory
    from app.models.inventory_risk import InventoryRiskAssessment
    from app.models.scrape_run import ScrapeRun
    from app.models.recommendation import Recommendation
    from app.models.reorder_recommendation import ReorderRecommendation
    from app.models.sales_record import SalesRecord
    from app.models.sales_velocity import SalesVelocity
    from app.models.stockout_prediction import StockoutPrediction
    from app.models.alert import Alert
    from app.models.seller import Seller
    from app.models.telegram_inventory_alert import TelegramInventoryAlert


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_category", "category"),
        Index("ix_products_searchable_text", "searchable_text"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    specifications: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    searchable_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    selling_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    supplier_lead_time: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_margin: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    seller: Mapped["Seller"] = relationship(back_populates="products")
    scrape_runs: Mapped[list["ScrapeRun"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    competitors: Mapped[list["Competitor"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    competitor_snapshots: Mapped[list["CompetitorSnapshot"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    competitor_events: Mapped[list["CompetitorEvent"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    competitor_rankings: Mapped[list["CompetitorRanking"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    market_opportunities: Mapped[list["MarketOpportunity"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    inventory_history: Mapped[list["InventoryHistory"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    sales_records: Mapped[list["SalesRecord"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    sales_velocity: Mapped[list["SalesVelocity"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    stockout_predictions: Mapped[list["StockoutPrediction"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    reorder_recommendations: Mapped[list["ReorderRecommendation"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    inventory_risk_assessments: Mapped[list["InventoryRiskAssessment"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    telegram_inventory_alerts: Mapped[list["TelegramInventoryAlert"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )

    @property
    def pricing_warning(self) -> str | None:
        if self.selling_price < self.cost_price:
            return "Selling price is below cost price."
        return None
