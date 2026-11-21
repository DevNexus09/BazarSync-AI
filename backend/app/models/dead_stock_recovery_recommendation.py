from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.dead_stock_assessment import DeadStockAssessment
    from app.models.product import Product
    from app.models.seller import Seller


EVIDENCE_RECOVERY_VERSION = "evidence-recovery-v1"


class DeadStockRecoveryAction(str, Enum):
    BUNDLE = "BUNDLE"
    DISCOUNT = "DISCOUNT"
    FLASH_SALE = "FLASH_SALE"
    SEO_FIX = "SEO_FIX"
    HOLD = "HOLD"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class DeadStockRecoveryRecommendationStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DeadStockRecoveryRecommendation(Base):
    __tablename__ = "dead_stock_recovery_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "dead_stock_assessment_id",
            "calculation_version",
            name="uq_dead_stock_recovery_assessment_version",
        ),
        CheckConstraint("recommended_discount_rate IS NULL OR (recommended_discount_rate >= 0 AND recommended_discount_rate < 1)", name="ck_dead_stock_recovery_discount_rate"),
        CheckConstraint("recommended_price IS NULL OR recommended_price >= 0", name="ck_dead_stock_recovery_price"),
        CheckConstraint("suggested_duration_days IS NULL OR suggested_duration_days > 0", name="ck_dead_stock_recovery_duration"),
        CheckConstraint("recommended_quantity IS NULL OR recommended_quantity >= 0", name="ck_dead_stock_recovery_quantity"),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_dead_stock_recovery_confidence"),
        Index("ix_dead_stock_recovery_seller_status", "seller_id", "recommendation_status"),
        Index("ix_dead_stock_recovery_product_generated", "product_id", "generated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    dead_stock_assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("dead_stock_assessments.id", ondelete="CASCADE"), nullable=False)
    primary_action: Mapped[DeadStockRecoveryAction] = mapped_column(SAEnum(DeadStockRecoveryAction, name="dead_stock_recovery_action"), nullable=False)
    secondary_actions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    recommended_discount_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    recommended_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    suggested_duration_days: Mapped[int | None] = mapped_column(nullable=True)
    recommended_quantity: Mapped[int | None] = mapped_column(nullable=True)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    recommendation_status: Mapped[DeadStockRecoveryRecommendationStatus] = mapped_column(
        SAEnum(DeadStockRecoveryRecommendationStatus, name="dead_stock_recovery_status"),
        nullable=False,
    )
    explanation: Mapped[str] = mapped_column(String(1000), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rejected_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    calculation_version: Mapped[str] = mapped_column(String(20), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="dead_stock_recovery_recommendations")
    product: Mapped["Product"] = relationship(back_populates="dead_stock_recovery_recommendations")
    dead_stock_assessment: Mapped["DeadStockAssessment"] = relationship(back_populates="recovery_recommendations")
