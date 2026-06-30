from __future__ import annotations

from datetime import datetime
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.competitor_snapshot import CompetitorSnapshot
    from app.models.competitor_event import CompetitorEvent
    from app.models.competitor_ranking import CompetitorRanking
    from app.models.market_opportunity import MarketOpportunity
    from app.models.price_history import PriceHistory
    from app.models.product import Product
    from app.models.scrape_run import ScrapeRun


class Competitor(Base):
    __tablename__ = "competitors"
    __table_args__ = (
        Index("ix_competitors_product_id", "product_id"),
        Index("ix_competitors_scrape_run_id", "scrape_run_id"),
        Index("ix_competitors_similarity_score", "similarity_score"),
        Index("ix_competitors_ranking_score", "ranking_score"),
        Index("ix_competitors_match_confidence", "match_confidence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    scrape_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scrape_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )

    competitor_title: Mapped[str] = mapped_column(String(255), nullable=False)
    competitor_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    competitor_category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    competitor_brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    competitor_attributes: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    competitor_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    discount_percentage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    competitor_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    competitor_sold: Mapped[str | None] = mapped_column(String(50), nullable=True)
    competitor_store: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stock_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    title_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    description_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    attribute_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    keyword_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ranking_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    matched_attributes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    marketplace: Mapped[str] = mapped_column(String(120), nullable=False)
    product_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    product: Mapped["Product"] = relationship(back_populates="competitors")
    scrape_run: Mapped["ScrapeRun"] = relationship(back_populates="competitors")
    price_history: Mapped[list["PriceHistory"]] = relationship(
        back_populates="competitor",
        cascade="all, delete-orphan",
    )
    snapshots: Mapped[list["CompetitorSnapshot"]] = relationship(
        back_populates="competitor",
    )
    events: Mapped[list["CompetitorEvent"]] = relationship(
        back_populates="competitor",
    )
    rankings: Mapped[list["CompetitorRanking"]] = relationship(
        back_populates="competitor",
    )
    market_opportunities: Mapped[list["MarketOpportunity"]] = relationship(
        back_populates="competitor",
    )
