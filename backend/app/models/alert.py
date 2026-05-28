from __future__ import annotations

from datetime import datetime
import uuid
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.recommendation import Recommendation
    from app.models.seller import Seller
    from app.models.alert_delivery_log import AlertDeliveryLog


class AlertDeliveryStatus(str, Enum):
    delivered = "delivered"
    failed = "failed"
    pending = "pending"
    duplicate = "duplicate"


class AlertUrgencyLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertActionType(str, Enum):
    PRICE_LOWER = "PRICE_LOWER"
    PRICE_RAISE = "PRICE_RAISE"
    HOLD = "HOLD"
    REORDER = "REORDER"
    STOCK_WARNING = "STOCK_WARNING"
    OPPORTUNITY_CAPTURE = "OPPORTUNITY_CAPTURE"


class AlertConfidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_seller_id", "seller_id"),
        Index("ix_alerts_product_id", "product_id"),
        Index("ix_alerts_recommendation_id", "recommendation_id"),
        Index("ix_alerts_delivery_status", "delivery_status"),
        Index("ix_alerts_urgency_level", "urgency_level"),
        Index("ix_alerts_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
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
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="SET NULL"),
        nullable=True,
    )
    alert_type: Mapped[str] = mapped_column(String(120), nullable=False, default="urgency_alert")
    urgency_level: Mapped[AlertUrgencyLevel] = mapped_column(
        SAEnum(AlertUrgencyLevel, name="alert_urgency_level"),
        nullable=False,
        default=AlertUrgencyLevel.MEDIUM,
    )
    action_type: Mapped[AlertActionType] = mapped_column(
        SAEnum(AlertActionType, name="alert_action_type"),
        nullable=False,
    )
    confidence: Mapped[AlertConfidence] = mapped_column(
        SAEnum(AlertConfidence, name="alert_confidence"),
        nullable=False,
    )
    delivery_status: Mapped[AlertDeliveryStatus] = mapped_column(
        SAEnum(AlertDeliveryStatus, name="alert_delivery_status"),
        nullable=False,
        default=AlertDeliveryStatus.pending,
    )
    telegram_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    product: Mapped["Product"] = relationship(back_populates="alerts")
    seller: Mapped["Seller"] = relationship(back_populates="alerts")
    recommendation: Mapped["Recommendation | None"] = relationship(back_populates="alerts")
    delivery_logs: Mapped[list["AlertDeliveryLog"]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
    )
