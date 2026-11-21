from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.competitor import Competitor
    from app.models.product import Product
    from app.models.scrape_run import ScrapeRun


class CompetitorSnapshot(Base):
    __tablename__ = "competitor_snapshots"
    __table_args__ = (
        CheckConstraint("price IS NULL OR price >= 0", name="ck_competitor_snapshots_price_nonnegative"),
        CheckConstraint("rating IS NULL OR (rating >= 0 AND rating <= 5)", name="ck_competitor_snapshots_rating_range"),
        CheckConstraint("review_count IS NULL OR review_count >= 0", name="ck_competitor_snapshots_review_count_nonnegative"),
        CheckConstraint(
            "stock_status IN ('IN_STOCK', 'OUT_OF_STOCK', 'UNKNOWN')",
            name="ck_competitor_snapshots_stock_status",
        ),
        UniqueConstraint(
            "scrape_run_id",
            "competitor_id",
            "product_id",
            name="uq_competitor_snapshots_run_competitor_product",
        ),
        Index("ix_competitor_snapshots_scrape_run_id", "scrape_run_id"),
        Index("ix_competitor_snapshots_product_captured", "product_id", "captured_at"),
        Index(
            "ix_competitor_snapshots_competitor_product_captured",
            "competitor_id",
            "product_id",
            "captured_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    scrape_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scrape_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competitors.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), server_default="BDT", nullable=False)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_status: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_stock_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_listing_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stock_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    match_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    scrape_run: Mapped["ScrapeRun"] = relationship(back_populates="snapshots")
    competitor: Mapped["Competitor"] = relationship(back_populates="snapshots")
    product: Mapped["Product"] = relationship(back_populates="competitor_snapshots")
