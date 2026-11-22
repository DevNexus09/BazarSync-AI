from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import uuid

from sqlalchemy import CheckConstraint, Date, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BusinessExpenseType(str, Enum):
    ADVERTISING = "ADVERTISING"
    SHIPPING = "SHIPPING"
    PACKAGING = "PACKAGING"
    SUPPLIER_PURCHASE = "SUPPLIER_PURCHASE"
    RENT = "RENT"
    SALARY = "SALARY"
    UTILITIES = "UTILITIES"
    OTHER = "OTHER"


class BusinessExpenseStatus(str, Enum):
    PAID = "PAID"
    DUE = "DUE"


class BusinessExpense(Base):
    """A seller's operating cost or supplier bill; DUE rows are money still owed."""

    __tablename__ = "business_expenses"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_business_expenses_amount_nonnegative"),
        Index("ix_business_expenses_seller_incurred_at", "seller_id", "incurred_at"),
        Index("ix_business_expenses_seller_status", "seller_id", "payment_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    expense_type: Mapped[BusinessExpenseType] = mapped_column(SAEnum(BusinessExpenseType, name="business_expense_type"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BDT", server_default="BDT")
    incurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payment_status: Mapped[BusinessExpenseStatus] = mapped_column(SAEnum(BusinessExpenseStatus, name="business_expense_status"), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    counterparty: Mapped[str | None] = mapped_column(String(160), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="MANUAL", server_default="MANUAL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class MarketplaceStoreMetric(Base):
    """Store-level marketplace scorecard (seller rating etc.) captured at a point in time."""

    __tablename__ = "marketplace_store_metrics"
    __table_args__ = (Index("ix_marketplace_store_metrics_seller_captured_at", "seller_id", "captured_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(120), nullable=False)
    seller_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    positive_rating_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    ship_on_time_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    chat_response_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="MANUAL", server_default="MANUAL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
