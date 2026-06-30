from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Date, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class SalesVelocityDataStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    LIMITED = "LIMITED"
    INSUFFICIENT = "INSUFFICIENT"


class SalesVelocity(Base):
    __tablename__ = "sales_velocity"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "as_of_date",
            "window_days",
            "calculation_version",
            name="uq_sales_velocity_product_date_window_version",
        ),
        CheckConstraint("window_days > 0", name="ck_sales_velocity_window_days_positive"),
        CheckConstraint("observed_days >= 1", name="ck_sales_velocity_observed_days_positive"),
        CheckConstraint("gross_units_sold >= 0", name="ck_sales_velocity_gross_nonnegative"),
        CheckConstraint("returned_units >= 0", name="ck_sales_velocity_returned_nonnegative"),
        CheckConstraint("net_units_sold >= 0", name="ck_sales_velocity_net_nonnegative"),
        CheckConstraint("daily_sales_rate >= 0", name="ck_sales_velocity_rate_nonnegative"),
        CheckConstraint("sales_days >= 0", name="ck_sales_velocity_sales_days_nonnegative"),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_sales_velocity_confidence_range"),
        Index("ix_sales_velocity_product_as_of_date", "product_id", "as_of_date"),
        Index("ix_sales_velocity_seller_as_of_date", "seller_id", "as_of_date"),
        Index("ix_sales_velocity_product_calculated", "product_id", "calculated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_days: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_units_sold: Mapped[int] = mapped_column(Integer, nullable=False)
    returned_units: Mapped[int] = mapped_column(Integer, nullable=False)
    net_units_sold: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_sales_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    sales_days: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    data_status: Mapped[SalesVelocityDataStatus] = mapped_column(
        SAEnum(SalesVelocityDataStatus, name="sales_velocity_data_status"),
        nullable=False,
    )
    calculation_version: Mapped[str] = mapped_column(String(20), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculation_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    seller: Mapped["Seller"] = relationship(back_populates="sales_velocity")
    product: Mapped["Product"] = relationship(back_populates="sales_velocity")
