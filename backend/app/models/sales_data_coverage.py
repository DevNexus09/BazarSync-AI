from __future__ import annotations

from datetime import date, datetime
from enum import Enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class SalesDataCompletenessStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"


class SalesDataCoverage(Base):
    __tablename__ = "sales_data_coverage"
    __table_args__ = (
        CheckConstraint("coverage_end_date >= coverage_start_date", name="ck_sales_data_coverage_date_order"),
        CheckConstraint("imported_record_count >= 0", name="ck_sales_data_coverage_imported_nonnegative"),
        CheckConstraint("valid_sales_count >= 0", name="ck_sales_data_coverage_valid_nonnegative"),
        CheckConstraint("invalid_or_excluded_count >= 0", name="ck_sales_data_coverage_invalid_nonnegative"),
        Index("ix_sales_data_coverage_seller_dates", "seller_id", "coverage_start_date", "coverage_end_date"),
        Index("ix_sales_data_coverage_product_id", "product_id"),
        Index("ix_sales_data_coverage_marketplace", "marketplace"),
        Index("ix_sales_data_coverage_seller_marketplace_status", "seller_id", "marketplace", "completeness_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    marketplace: Mapped[str | None] = mapped_column(String(120), nullable=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    coverage_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    completeness_status: Mapped[SalesDataCompletenessStatus] = mapped_column(
        SAEnum(SalesDataCompletenessStatus, name="sales_data_completeness_status"),
        nullable=False,
        default=SalesDataCompletenessStatus.UNKNOWN,
        server_default=SalesDataCompletenessStatus.UNKNOWN.value,
    )
    imported_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    valid_sales_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    invalid_or_excluded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="sales_data_coverage")
    product: Mapped["Product | None"] = relationship(back_populates="sales_data_coverage")
