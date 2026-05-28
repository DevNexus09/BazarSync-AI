from __future__ import annotations

from datetime import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.alert import AlertDeliveryStatus

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.seller import Seller


class AlertDeliveryLog(Base):
    __tablename__ = "alert_delivery_logs"
    __table_args__ = (
        Index("ix_alert_delivery_logs_seller_id", "seller_id"),
        Index("ix_alert_delivery_logs_alert_id", "alert_id"),
        Index("ix_alert_delivery_logs_status", "delivery_status"),
        Index("ix_alert_delivery_logs_sent_at", "sent_at"),
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
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("alerts.id", ondelete="CASCADE"),
        nullable=False,
    )
    telegram_chat_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    delivery_status: Mapped[AlertDeliveryStatus] = mapped_column(
        SAEnum(AlertDeliveryStatus, name="alert_delivery_status"),
        nullable=False,
        default=AlertDeliveryStatus.pending,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    seller: Mapped["Seller"] = relationship(back_populates="alert_delivery_logs")
    alert: Mapped["Alert"] = relationship(back_populates="delivery_logs")
