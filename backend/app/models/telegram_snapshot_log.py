from __future__ import annotations

from datetime import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class TelegramProductSnapshotLog(Base):
    __tablename__ = "snapshot_logs"
    __table_args__ = (
        Index("ix_snapshot_logs_seller_id", "seller_id"),
        Index("ix_snapshot_logs_product_id", "product_id"),
        Index("ix_snapshot_logs_status", "status"),
        Index("ix_snapshot_logs_sent_at", "sent_at"),
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
    telegram_chat_id: Mapped[str] = mapped_column(String(120), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    seller: Mapped["Seller"] = relationship(back_populates="snapshot_logs")
    product: Mapped["Product"] = relationship()
