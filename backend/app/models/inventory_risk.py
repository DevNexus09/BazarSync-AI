from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Date, DateTime, Enum as SAEnum, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.reorder_recommendation import ReorderRecommendation
    from app.models.seller import Seller
    from app.models.stockout_prediction import StockoutPrediction


class InventoryRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class InventoryRiskDataStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    LIMITED = "LIMITED"
    INSUFFICIENT = "INSUFFICIENT"


class InventoryRiskAssessment(Base):
    __tablename__ = "inventory_risk_assessments"
    __table_args__ = (
        UniqueConstraint("product_id", "as_of_date", "calculation_version", name="uq_inventory_risk_product_date_version"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="ck_inventory_risk_score_range"),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_inventory_risk_confidence_range"),
        Index("ix_inventory_risk_seller_level", "seller_id", "risk_level"),
        Index("ix_inventory_risk_product_as_of_date", "product_id", "as_of_date"),
        Index("ix_inventory_risk_assessed_at", "assessed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    stockout_prediction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("stockout_predictions.id", ondelete="SET NULL"), nullable=True)
    reorder_recommendation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("reorder_recommendations.id", ondelete="SET NULL"), nullable=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    risk_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    risk_level: Mapped[InventoryRiskLevel | None] = mapped_column(SAEnum(InventoryRiskLevel, name="inventory_risk_level"), nullable=True)
    coverage_gap_days: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    data_status: Mapped[InventoryRiskDataStatus] = mapped_column(SAEnum(InventoryRiskDataStatus, name="inventory_risk_data_status"), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    factors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(20), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="inventory_risk_assessments")
    product: Mapped["Product"] = relationship(back_populates="inventory_risk_assessments")
    stockout_prediction: Mapped["StockoutPrediction | None"] = relationship()
    reorder_recommendation: Mapped["ReorderRecommendation | None"] = relationship()
