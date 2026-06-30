from __future__ import annotations

from datetime import date, datetime
from enum import Enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class InventorySnapshotSource(str, Enum):
    DAILY_SNAPSHOT = "DAILY_SNAPSHOT"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    MARKETPLACE_SYNC = "MARKETPLACE_SYNC"
    BACKFILL = "BACKFILL"


class InventoryHistory(Base):
    __tablename__ = "inventory_history"
    __table_args__ = (
        UniqueConstraint(
            "seller_id",
            "product_id",
            "snapshot_date",
            name="uq_inventory_history_seller_product_date",
        ),
        CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_history_on_hand_nonnegative"),
        CheckConstraint("quantity_reserved >= 0", name="ck_inventory_history_reserved_nonnegative"),
        CheckConstraint("quantity_incoming >= 0", name="ck_inventory_history_incoming_nonnegative"),
        CheckConstraint(
            "quantity_available = quantity_on_hand - quantity_reserved",
            name="ck_inventory_history_available_definition",
        ),
        Index("ix_inventory_history_product_snapshot_date", "product_id", "snapshot_date"),
        Index("ix_inventory_history_seller_snapshot_date", "seller_id", "snapshot_date"),
        Index("ix_inventory_history_product_captured", "product_id", "captured_at"),
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
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_available: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_incoming: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[InventorySnapshotSource] = mapped_column(
        SAEnum(InventorySnapshotSource, name="inventory_snapshot_source"),
        nullable=False,
    )
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    seller: Mapped["Seller"] = relationship(back_populates="inventory_history")
    product: Mapped["Product"] = relationship(back_populates="inventory_history")
