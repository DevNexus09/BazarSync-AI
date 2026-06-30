from __future__ import annotations

from datetime import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.competitor import Competitor
    from app.models.competitor_event import CompetitorEvent
    from app.models.competitor_ranking import CompetitorRanking
    from app.models.market_opportunity import MarketOpportunity
    from app.models.competitor_snapshot import CompetitorSnapshot
    from app.models.product import Product
    from app.models.seller import Seller


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'PARTIAL')",
            name="ck_scrape_runs_status",
        ),
        UniqueConstraint("seller_id", "product_id", "marketplace", "run_key", name="uq_scrape_runs_scope_run_key"),
        Index("ix_scrape_runs_seller_id", "seller_id"),
        Index("ix_scrape_runs_product_id", "product_id"),
        Index("ix_scrape_runs_status", "status"),
        Index("ix_scrape_runs_product_status_finished", "product_id", "status", "finished_at"),
        Index("ix_scrape_runs_product_marketplace_created", "product_id", "marketplace", "created_at"),
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
    marketplace: Mapped[str] = mapped_column(String(120), server_default="Daraz Bangladesh", nullable=False)
    run_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), server_default="PENDING", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_results: Mapped[int | None] = mapped_column(Integer, nullable=True)
    successful_matches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discovered_competitor_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
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

    seller: Mapped["Seller"] = relationship(back_populates="scrape_runs")
    product: Mapped["Product"] = relationship(back_populates="scrape_runs")
    competitors: Mapped[list["Competitor"]] = relationship(
        back_populates="scrape_run",
        cascade="all, delete-orphan",
    )
    snapshots: Mapped[list["CompetitorSnapshot"]] = relationship(
        back_populates="scrape_run",
    )
    competitor_events: Mapped[list["CompetitorEvent"]] = relationship(
        back_populates="scrape_run",
        cascade="all, delete-orphan",
    )
    competitor_rankings: Mapped[list["CompetitorRanking"]] = relationship(
        back_populates="scrape_run",
        cascade="all, delete-orphan",
    )
    market_opportunities: Mapped[list["MarketOpportunity"]] = relationship(
        back_populates="scrape_run",
        cascade="all, delete-orphan",
    )
