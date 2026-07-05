from __future__ import annotations

from datetime import datetime
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.inventory_risk import InventoryRiskAssessment
    from app.models.product import Product
    from app.models.reorder_recommendation import ReorderRecommendation
    from app.models.seller import Seller


class TelegramInventoryAlertType(str, Enum):
    CRITICAL_RISK = "CRITICAL_RISK"
    HIGH_RISK = "HIGH_RISK"
    RISK_ESCALATION = "RISK_ESCALATION"
    REORDER_DEADLINE = "REORDER_DEADLINE"
    DAYS_REMAINING_DROP = "DAYS_REMAINING_DROP"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    DEAD_STOCK_CLASSIFIED = "DEAD_STOCK_CLASSIFIED"
    DEAD_STOCK_CRITICAL_RISK = "DEAD_STOCK_CRITICAL_RISK"
    DEAD_STOCK_LOCKED_CAPITAL = "DEAD_STOCK_LOCKED_CAPITAL"
    DEAD_STOCK_RECOVERY_AVAILABLE = "DEAD_STOCK_RECOVERY_AVAILABLE"
    DEAD_STOCK_AGED = "DEAD_STOCK_AGED"


class TelegramInventoryAlertStatus(str, Enum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TelegramInventoryAlert(Base):
    __tablename__ = "telegram_inventory_alerts"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_telegram_inventory_alerts_dedupe_key"),
        Index("ix_telegram_inventory_alerts_seller_status", "seller_id", "status"),
        Index("ix_telegram_inventory_alerts_product_created", "product_id", "created_at"),
        Index("ix_telegram_inventory_alerts_next_attempt", "status", "next_attempt_at"),
        Index("ix_telegram_inventory_alerts_risk", "risk_assessment_id"),
        Index("ix_telegram_inventory_alerts_reorder", "reorder_recommendation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    risk_assessment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("inventory_risk_assessments.id", ondelete="CASCADE"), nullable=True)
    reorder_recommendation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("reorder_recommendations.id", ondelete="SET NULL"), nullable=True)
    alert_type: Mapped[TelegramInventoryAlertType] = mapped_column(
        SAEnum(TelegramInventoryAlertType, name="telegram_inventory_alert_type"),
        nullable=False,
    )
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[TelegramInventoryAlertStatus] = mapped_column(
        SAEnum(TelegramInventoryAlertStatus, name="telegram_inventory_alert_status"),
        nullable=False,
        default=TelegramInventoryAlertStatus.PENDING,
    )
    message_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    alert_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="telegram_inventory_alerts")
    product: Mapped["Product"] = relationship(back_populates="telegram_inventory_alerts")
    risk_assessment: Mapped["InventoryRiskAssessment | None"] = relationship()
    reorder_recommendation: Mapped["ReorderRecommendation | None"] = relationship()
