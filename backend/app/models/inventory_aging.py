from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Date, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.inventory_history import InventoryHistory
    from app.models.product import Product
    from app.models.seller import Seller


class InventoryAgeSource(str, Enum):
    INVENTORY_LOT = "INVENTORY_LOT"
    PURCHASE_RECEIPT = "PURCHASE_RECEIPT"
    INVENTORY_TRANSACTION = "INVENTORY_TRANSACTION"
    FIRST_POSITIVE_SNAPSHOT = "FIRST_POSITIVE_SNAPSHOT"
    PRODUCT_CREATED_AT_ESTIMATE = "PRODUCT_CREATED_AT_ESTIMATE"
    UNAVAILABLE = "UNAVAILABLE"


class InventoryAgingSnapshot(Base):
    __tablename__ = "inventory_aging_snapshots"
    __table_args__ = (
        UniqueConstraint("product_id", "as_of_date", "calculation_version", name="uq_inventory_aging_product_date_version"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_aging_on_hand_nonnegative"),
        CheckConstraint("quantity_reserved >= 0", name="ck_inventory_aging_reserved_nonnegative"),
        CheckConstraint("quantity_available >= 0", name="ck_inventory_aging_available_nonnegative"),
        CheckConstraint("eligible_unsold_quantity >= 0", name="ck_inventory_aging_eligible_nonnegative"),
        CheckConstraint("oldest_age_days IS NULL OR oldest_age_days >= 0", name="ck_inventory_aging_oldest_nonnegative"),
        CheckConstraint("newest_age_days IS NULL OR newest_age_days >= 0", name="ck_inventory_aging_newest_nonnegative"),
        CheckConstraint(
            "weighted_average_age_days IS NULL OR weighted_average_age_days >= 0",
            name="ck_inventory_aging_weighted_nonnegative",
        ),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_inventory_aging_confidence_range"),
        Index("ix_inventory_aging_seller_as_of_date", "seller_id", "as_of_date"),
        Index("ix_inventory_aging_product_as_of_date", "product_id", "as_of_date"),
        Index("ix_inventory_aging_product_calculated", "product_id", "calculated_at"),
        Index("ix_inventory_aging_oldest_age", "oldest_age_days"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    inventory_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_history.id", ondelete="SET NULL"),
        nullable=True,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_available: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_unsold_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    oldest_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    newest_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weighted_average_age_days: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    age_source: Mapped[InventoryAgeSource] = mapped_column(
        SAEnum(InventoryAgeSource, name="inventory_age_source"),
        nullable=False,
    )
    is_estimated: Mapped[bool] = mapped_column(nullable=False, default=True)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    age_buckets: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(20), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="inventory_aging_snapshots")
    product: Mapped["Product"] = relationship(back_populates="inventory_aging_snapshots")
    inventory_snapshot: Mapped["InventoryHistory | None"] = relationship()
