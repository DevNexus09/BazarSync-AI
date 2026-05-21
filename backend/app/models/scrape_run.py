from __future__ import annotations

from datetime import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.competitor import Competitor
    from app.models.product import Product
    from app.models.seller import Seller


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    __table_args__ = (
        Index("ix_scrape_runs_seller_id", "seller_id"),
        Index("ix_scrape_runs_product_id", "product_id"),
        Index("ix_scrape_runs_status", "status"),
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
    status: Mapped[str] = mapped_column(String(30), server_default="pending", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_results: Mapped[int | None] = mapped_column(Integer, nullable=True)
    successful_matches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    seller: Mapped["Seller"] = relationship(back_populates="scrape_runs")
    product: Mapped["Product"] = relationship(back_populates="scrape_runs")
    competitors: Mapped[list["Competitor"]] = relationship(
        back_populates="scrape_run",
        cascade="all, delete-orphan",
    )
