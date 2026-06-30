from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.competitor import Competitor
    from app.models.competitor_snapshot import CompetitorSnapshot
    from app.models.product import Product
    from app.models.scrape_run import ScrapeRun
    from app.models.seller import Seller
    from app.models.market_opportunity import MarketOpportunity


class CompetitorEventType(str, Enum):
    PRICE_DROP = "PRICE_DROP"
    PRICE_RISE = "PRICE_RISE"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    BACK_IN_STOCK = "BACK_IN_STOCK"
    NEW_COMPETITOR = "NEW_COMPETITOR"
    COMPETITOR_REMOVED = "COMPETITOR_REMOVED"


class CompetitorEventSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CompetitorEvent(Base):
    __tablename__ = "competitor_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_competitor_events_dedupe_key"),
        Index("ix_competitor_events_product_detected", "product_id", "detected_at"),
        Index("ix_competitor_events_competitor_detected", "competitor_id", "detected_at"),
        Index("ix_competitor_events_type_detected", "event_type", "detected_at"),
        Index("ix_competitor_events_scrape_run_id", "scrape_run_id"),
        Index("ix_competitor_events_seller_detected", "seller_id", "detected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competitors.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scrape_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scrape_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    previous_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competitor_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    current_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competitor_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[CompetitorEventType] = mapped_column(
        SAEnum(CompetitorEventType, name="competitor_event_type"),
        nullable=False,
    )
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    price_change_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_change_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    severity: Mapped[CompetitorEventSeverity] = mapped_column(
        SAEnum(CompetitorEventSeverity, name="competitor_event_severity"),
        nullable=False,
    )
    dedupe_key: Mapped[str] = mapped_column(String(500), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    seller: Mapped["Seller"] = relationship(back_populates="competitor_events")
    product: Mapped["Product"] = relationship(back_populates="competitor_events")
    competitor: Mapped["Competitor"] = relationship(back_populates="events")
    scrape_run: Mapped["ScrapeRun"] = relationship(back_populates="competitor_events")
    previous_snapshot: Mapped["CompetitorSnapshot | None"] = relationship(
        foreign_keys=[previous_snapshot_id],
    )
    current_snapshot: Mapped["CompetitorSnapshot | None"] = relationship(
        foreign_keys=[current_snapshot_id],
    )
    market_opportunity: Mapped["MarketOpportunity | None"] = relationship(
        back_populates="trigger_event",
        uselist=False,
    )
