from __future__ import annotations

from datetime import datetime
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class ActionCenterItemStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLETED = "COMPLETED"
    DISMISSED = "DISMISSED"
    EXPIRED = "EXPIRED"


class ActionCenterPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ActionCenterItem(Base):
    __tablename__ = "action_center_items"
    __table_args__ = (
        UniqueConstraint("seller_id", "source_type", "source_id", name="uq_action_center_items_source"),
        Index("ix_action_center_items_seller_status", "seller_id", "status"),
        Index("ix_action_center_items_product_status", "product_id", "status"),
        Index("ix_action_center_items_priority_due", "priority", "due_at"),
        Index("ix_action_center_items_source", "source_type", "source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    source_domain: Mapped[str] = mapped_column(String(80), nullable=False)
    source_type: Mapped[str] = mapped_column(String(120), nullable=False)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    action_type: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[ActionCenterPriority] = mapped_column(SAEnum(ActionCenterPriority, name="action_center_priority"), nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expected_impact_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ActionCenterItemStatus] = mapped_column(
        SAEnum(ActionCenterItemStatus, name="action_center_item_status"),
        nullable=False,
        default=ActionCenterItemStatus.OPEN,
        server_default=ActionCenterItemStatus.OPEN.value,
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    seller: Mapped["Seller"] = relationship(back_populates="action_center_items")
    product: Mapped["Product | None"] = relationship()
