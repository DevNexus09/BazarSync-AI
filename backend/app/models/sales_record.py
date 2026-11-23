from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
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


class SalesRecordPriceSource(str, Enum):
    TRANSACTION = "TRANSACTION"
    IMPORTED_TRANSACTION = "IMPORTED_TRANSACTION"
    CURRENT_PRODUCT_PRICE_ESTIMATE = "CURRENT_PRODUCT_PRICE_ESTIMATE"
    UNKNOWN = "UNKNOWN"


class SalesRecord(Base):
    __tablename__ = "sales_records"
    __table_args__ = (
        UniqueConstraint("seller_id", "source_reference", name="uq_sales_records_seller_source_reference"),
        CheckConstraint("quantity_sold > 0", name="ck_sales_records_quantity_sold_positive"),
        CheckConstraint("returned_units >= 0", name="ck_sales_records_returned_units_nonnegative"),
        CheckConstraint("refunded_restocked_units >= 0", name="ck_sales_records_refunded_restocked_nonnegative"),
        CheckConstraint("unit_price IS NULL OR unit_price >= 0", name="ck_sales_records_unit_price_nonnegative"),
        CheckConstraint("line_total IS NULL OR line_total >= 0", name="ck_sales_records_line_total_nonnegative"),
        CheckConstraint("unit_price IS NULL OR currency IS NULL OR length(currency) = 3", name="ck_sales_records_currency_length"),
        Index("ix_sales_records_product_sold_at", "product_id", "sold_at"),
        Index("ix_sales_records_seller_sold_at", "seller_id", "sold_at"),
        Index("ix_sales_records_status_sold_at", "status", "sold_at"),
        Index("ix_sales_records_marketplace_listing_id", "marketplace_listing_id"),
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
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[SalesRecordStatus] = mapped_column(
        SAEnum(SalesRecordStatus, name="sales_record_status"),
        nullable=False,
    )
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity_sold: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    marketplace_listing_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Opaque marketplace buyer reference (never a name or phone) and delivery district; NULL = not imported.
    customer_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delivery_district: Mapped[str | None] = mapped_column(String(80), nullable=True)
    price_source: Mapped[SalesRecordPriceSource] = mapped_column(
        SAEnum(SalesRecordPriceSource, name="sales_record_price_source"),
        nullable=False,
        default=SalesRecordPriceSource.UNKNOWN,
        server_default=SalesRecordPriceSource.UNKNOWN.value,
    )
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
