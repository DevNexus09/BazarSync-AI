from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Date, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.inventory_history import InventoryHistory
    from app.models.product import Product
    from app.models.sales_velocity import SalesVelocity
    from app.models.seller import Seller
    from app.models.stockout_prediction import StockoutPrediction


FORECAST_REORDER_VERSION = "forecast-reorder-v1"


class ReorderRecommendationAction(str, Enum):
    HOLD = "HOLD"
    REORDER = "REORDER"


class ReorderRecommendationStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ORDERED = "ORDERED"
    DISMISSED = "DISMISSED"
    EXPIRED = "EXPIRED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ReorderRecommendation(Base):
    __tablename__ = "reorder_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "as_of_date",
            "calculation_version",
            name="uq_reorder_recommendations_product_date_version",
        ),
        CheckConstraint("recommended_quantity >= 0", name="ck_reorder_recommendations_quantity_nonnegative"),
        CheckConstraint("supplier_lead_time_days >= 0", name="ck_reorder_recommendations_lead_nonnegative"),
        CheckConstraint("safety_buffer_days >= 0", name="ck_reorder_recommendations_buffer_nonnegative"),
        CheckConstraint("review_period_days >= 0", name="ck_reorder_recommendations_review_nonnegative"),
        CheckConstraint("reorder_point >= 0", name="ck_reorder_recommendations_point_nonnegative"),
        CheckConstraint("target_stock >= 0", name="ck_reorder_recommendations_target_nonnegative"),
        CheckConstraint("daily_sales_rate >= 0", name="ck_reorder_recommendations_rate_nonnegative"),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_reorder_recommendations_confidence_range"),
        Index("ix_reorder_recommendations_product_as_of_date", "product_id", "as_of_date"),
        Index("ix_reorder_recommendations_seller_status", "seller_id", "recommendation_status"),
        Index("ix_reorder_recommendations_deadline", "reorder_deadline"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    inventory_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("inventory_history.id", ondelete="SET NULL"), nullable=True)
    sales_velocity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sales_velocity.id", ondelete="SET NULL"), nullable=True)
    stockout_prediction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("stockout_predictions.id", ondelete="SET NULL"), nullable=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    action: Mapped[ReorderRecommendationAction] = mapped_column(
        SAEnum(ReorderRecommendationAction, name="reorder_recommendation_action"),
        nullable=False,
    )
    recommended_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reorder_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier_lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    safety_buffer_days: Mapped[int] = mapped_column(Integer, nullable=False)
    review_period_days: Mapped[int] = mapped_column(Integer, nullable=False)
    reorder_point: Mapped[int] = mapped_column(Integer, nullable=False)
    target_stock: Mapped[int] = mapped_column(Integer, nullable=False)
    inventory_position: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_sales_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    recommendation_status: Mapped[ReorderRecommendationStatus] = mapped_column(
        SAEnum(ReorderRecommendationStatus, name="reorder_recommendation_status"),
        nullable=False,
    )
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(20), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="reorder_recommendations")
    product: Mapped["Product"] = relationship(back_populates="reorder_recommendations")
    inventory_snapshot: Mapped["InventoryHistory | None"] = relationship()
    sales_velocity: Mapped["SalesVelocity | None"] = relationship()
    stockout_prediction: Mapped["StockoutPrediction | None"] = relationship()
