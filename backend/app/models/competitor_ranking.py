from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.competitor import Competitor
    from app.models.product import Product
    from app.models.scrape_run import ScrapeRun
    from app.models.seller import Seller


class CompetitorRanking(Base):
    __tablename__ = "competitor_rankings"
    __table_args__ = (
        UniqueConstraint(
            "scrape_run_id",
            "competitor_id",
            "formula_version",
            name="uq_competitor_rankings_run_competitor_formula",
        ),
        Index("ix_competitor_rankings_product_calculated", "product_id", "calculated_at"),
        Index("ix_competitor_rankings_run_rank", "scrape_run_id", "market_rank"),
        Index("ix_competitor_rankings_competitor_calculated", "competitor_id", "calculated_at"),
        Index("ix_competitor_rankings_seller_calculated", "seller_id", "calculated_at"),
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
    price_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    rating_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    review_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    availability_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    market_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    formula_version: Mapped[str] = mapped_column(String(40), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    seller: Mapped["Seller"] = relationship(back_populates="competitor_rankings")
    product: Mapped["Product"] = relationship(back_populates="competitor_rankings")
    competitor: Mapped["Competitor"] = relationship(back_populates="rankings")
    scrape_run: Mapped["ScrapeRun"] = relationship(back_populates="competitor_rankings")
