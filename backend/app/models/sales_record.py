from __future__ import annotations

from datetime import datetime
from enum import Enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class SalesRecordStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    FAILED_PAYMENT = "FAILED_PAYMENT"


class SalesRecord(Base):
    __tablename__ = "sales_records"
    __table_args__ = (
        UniqueConstraint("seller_id", "source_reference", name="uq_sales_records_seller_source_reference"),
        CheckConstraint("quantity_sold >= 0", name="ck_sales_records_quantity_sold_nonnegative"),
        CheckConstraint("returned_units >= 0", name="ck_sales_records_returned_units_nonnegative"),
        CheckConstraint("refunded_restocked_units >= 0", name="ck_sales_records_refunded_restocked_nonnegative"),
        Index("ix_sales_records_product_sold_at", "product_id", "sold_at"),
        Index("ix_sales_records_seller_sold_at", "seller_id", "sold_at"),
        Index("ix_sales_records_status_sold_at", "status", "sold_at"),
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
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[SalesRecordStatus] = mapped_column(
        SAEnum(SalesRecordStatus, name="sales_record_status"),
        nullable=False,
    )
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity_sold: Mapped[int] = mapped_column(Integer, nullable=False)
    returned_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refunded_restocked_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_test_order: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    seller: Mapped["Seller"] = relationship(back_populates="sales_records")
    product: Mapped["Product"] = relationship(back_populates="sales_records")
