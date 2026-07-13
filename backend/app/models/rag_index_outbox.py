from __future__ import annotations

from datetime import datetime
from enum import Enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.rag_memory import RagMemorySourceType

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class RagIndexOutboxAction(str, Enum):
    UPSERT = "UPSERT"
    DELETE = "DELETE"


class RagIndexOutboxStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


class RagIndexOutbox(Base):
    """Durable, seller-scoped work queue for RAG source changes.

    The source payload is deliberately not copied here. Workers re-read the
    authoritative source row after claiming the event, which keeps this table
    small and prevents secrets from being persisted in the queue.
    """

    __tablename__ = "rag_index_outbox"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_rag_index_outbox_dedupe_key"),
        CheckConstraint("attempts >= 0", name="ck_rag_index_outbox_attempts_nonnegative"),
        Index("ix_rag_index_outbox_status_next_attempt", "status", "next_attempt_at"),
        Index("ix_rag_index_outbox_seller_id", "seller_id"),
        Index("ix_rag_index_outbox_source", "source_type", "source_id"),
        Index("ix_rag_index_outbox_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type: Mapped[RagMemorySourceType] = mapped_column(
        SAEnum(RagMemorySourceType, name="rag_memory_source_type"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[RagIndexOutboxAction] = mapped_column(
        SAEnum(RagIndexOutboxAction, name="rag_index_outbox_action"),
        nullable=False,
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[RagIndexOutboxStatus] = mapped_column(
        SAEnum(RagIndexOutboxStatus, name="rag_index_outbox_status"),
        nullable=False,
        default=RagIndexOutboxStatus.PENDING,
        server_default=RagIndexOutboxStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    seller: Mapped["Seller"] = relationship(back_populates="rag_index_outbox_events")
    product: Mapped["Product | None"] = relationship()
