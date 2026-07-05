from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class ProductVisibilityMetric(Base):
    __tablename__ = "product_visibility_metrics"
    __table_args__ = (
        CheckConstraint("impressions >= 0", name="ck_visibility_impressions_nonnegative"),
        CheckConstraint("views >= 0", name="ck_visibility_views_nonnegative"),
        CheckConstraint("clicks >= 0", name="ck_visibility_clicks_nonnegative"),
        CheckConstraint("search_rank IS NULL OR search_rank > 0", name="ck_visibility_search_rank_positive"),
        CheckConstraint("listing_quality_score IS NULL OR (listing_quality_score >= 0 AND listing_quality_score <= 100)", name="ck_visibility_quality_score_range"),
        CheckConstraint("conversion_rate IS NULL OR (conversion_rate >= 0 AND conversion_rate <= 1)", name="ck_visibility_conversion_rate_range"),
        UniqueConstraint("product_id", "marketplace", "metric_date", "source", name="uq_visibility_product_marketplace_date_source"),
        Index("ix_visibility_product_metric_date", "product_id", "metric_date"),
        Index("ix_visibility_seller_metric_date", "seller_id", "metric_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    search_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    listing_quality_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    conversion_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False, default="manual")
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship()
    product: Mapped["Product"] = relationship(back_populates="visibility_metrics")
