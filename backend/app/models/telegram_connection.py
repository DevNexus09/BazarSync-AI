from __future__ import annotations

from datetime import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.seller import Seller


class SellerTelegramConnection(Base):
    __tablename__ = "seller_telegram_connections"
    __table_args__ = (
        Index("ix_seller_telegram_connections_seller_id", "seller_id", unique=True),
        Index("ix_seller_telegram_connections_token", "connection_token"),
        Index("ix_seller_telegram_connections_chat_id", "telegram_chat_id"),
        Index("ix_seller_telegram_connections_is_connected", "is_connected"),
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
        unique=True,
    )
    telegram_chat_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    telegram_first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    telegram_last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    connection_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_alert_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    seller: Mapped["Seller"] = relationship(back_populates="telegram_connection")
