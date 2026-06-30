from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.competitor import Competitor
    from app.models.competitor_event import CompetitorEvent
    from app.models.product import Product
    from app.models.scrape_run import ScrapeRun
    from app.models.seller import Seller


class MarketOpportunityType(str, Enum):
    COMPETITOR_OUT_OF_STOCK = "COMPETITOR_OUT_OF_STOCK"
    COMPETITOR_PRICE_RISE = "COMPETITOR_PRICE_RISE"
    COMPETITOR_REMOVED = "COMPETITOR_REMOVED"


class MarketOpportunityLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MarketOpportunityStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"
    EXPIRED = "EXPIRED"
    RESOLVED = "RESOLVED"


class MarketOpportunityAction(str, Enum):
    PRICE_LOWER = "PRICE_LOWER"
    PRICE_RAISE = "PRICE_RAISE"
    HOLD = "HOLD"
    REORDER = "REORDER"


class MarketOpportunity(Base):
    __tablename__ = "market_opportunities"
    __table_args__ = (
        UniqueConstraint("trigger_event_id", name="uq_market_opportunities_trigger_event_id"),
        Index("ix_market_opportunities_seller_status_detected", "seller_id", "status", "detected_at"),
        Index("ix_market_opportunities_product_detected", "product_id", "detected_at"),
        Index("ix_market_opportunities_level_detected", "opportunity_level", "detected_at"),
        Index("ix_market_opportunities_scrape_run_id", "scrape_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("competitors.id", ondelete="SET NULL"), nullable=True)
    trigger_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("competitor_events.id", ondelete="CASCADE"), nullable=False)
    scrape_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=False)
    opportunity_type: Mapped[MarketOpportunityType] = mapped_column(SAEnum(MarketOpportunityType, name="market_opportunity_type"), nullable=False)
    opportunity_level: Mapped[MarketOpportunityLevel] = mapped_column(SAEnum(MarketOpportunityLevel, name="market_opportunity_level"), nullable=False)
    opportunity_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    estimated_revenue: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    estimated_revenue_currency: Mapped[str] = mapped_column(String(3), server_default="BDT", nullable=False)
    recommended_action: Mapped[MarketOpportunityAction] = mapped_column(SAEnum(MarketOpportunityAction, name="market_opportunity_action"), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[MarketOpportunityStatus] = mapped_column(SAEnum(MarketOpportunityStatus, name="market_opportunity_status"), nullable=False, default=MarketOpportunityStatus.OPEN)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="market_opportunities")
    product: Mapped["Product"] = relationship(back_populates="market_opportunities")
    competitor: Mapped["Competitor | None"] = relationship(back_populates="market_opportunities")
    trigger_event: Mapped["CompetitorEvent"] = relationship(back_populates="market_opportunity")
    scrape_run: Mapped["ScrapeRun"] = relationship(back_populates="market_opportunities")
