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
    from app.models.inventory_history import InventoryHistory
    from app.models.product import Product
    from app.models.sales_velocity import SalesVelocity
    from app.models.seller import Seller


class StockoutPredictionStatus(str, Enum):
    PREDICTED = "PREDICTED"
    ALREADY_OUT_OF_STOCK = "ALREADY_OUT_OF_STOCK"
    NO_RECENT_DEMAND = "NO_RECENT_DEMAND"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class StockoutPrediction(Base):
    __tablename__ = "stockout_predictions"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "as_of_date",
            "calculation_version",
            name="uq_stockout_predictions_product_date_version",
        ),
        CheckConstraint("daily_sales_rate >= 0", name="ck_stockout_predictions_rate_nonnegative"),
        CheckConstraint("days_remaining >= 0", name="ck_stockout_predictions_days_nonnegative"),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_stockout_predictions_confidence_range"),
        Index("ix_stockout_predictions_product_as_of_date", "product_id", "as_of_date"),
        Index("ix_stockout_predictions_seller_as_of_date", "seller_id", "as_of_date"),
        Index("ix_stockout_predictions_status_as_of_date", "prediction_status", "as_of_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    inventory_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_history.id", ondelete="SET NULL"),
        nullable=True,
    )
    sales_velocity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sales_velocity.id", ondelete="SET NULL"),
        nullable=True,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_reserved: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_incoming: Mapped[int] = mapped_column(Integer, nullable=False)
    inventory_position: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_sales_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    days_remaining: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    predicted_stockout_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    prediction_status: Mapped[StockoutPredictionStatus] = mapped_column(
        SAEnum(StockoutPredictionStatus, name="stockout_prediction_status"),
        nullable=False,
    )
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(20), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    explanation: Mapped[str] = mapped_column(String(500), nullable=False)
    calculation_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="stockout_predictions")
    product: Mapped["Product"] = relationship(back_populates="stockout_predictions")
    inventory_snapshot: Mapped["InventoryHistory | None"] = relationship()
    sales_velocity: Mapped["SalesVelocity | None"] = relationship()
