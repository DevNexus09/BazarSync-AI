from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class MarketplaceFeePolicy(Base):
    __tablename__ = "marketplace_fee_policies"
    __table_args__ = (
        CheckConstraint("percentage_commission_rate >= 0 AND percentage_commission_rate < 1", name="ck_marketplace_fee_commission_rate"),
        CheckConstraint("payment_fee_rate >= 0 AND payment_fee_rate < 1", name="ck_marketplace_fee_payment_rate"),
        CheckConstraint("percentage_commission_rate + payment_fee_rate < 1", name="ck_marketplace_fee_total_rate"),
        CheckConstraint("fixed_per_order_fee >= 0", name="ck_marketplace_fee_fixed_order"),
        CheckConstraint("fixed_per_unit_fee >= 0", name="ck_marketplace_fee_fixed_unit"),
        CheckConstraint("fulfilment_fee >= 0", name="ck_marketplace_fee_fulfilment"),
        CheckConstraint("shipping_subsidy >= 0", name="ck_marketplace_fee_shipping_subsidy"),
        CheckConstraint("other_variable_cost >= 0", name="ck_marketplace_fee_other_variable"),
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="ck_marketplace_fee_effective_period"),
        UniqueConstraint("seller_id", "marketplace", "product_id", "category", "version", name="uq_marketplace_fee_policy_version"),
        Index("ix_marketplace_fee_seller_marketplace_active", "seller_id", "marketplace", "is_active"),
        Index("ix_marketplace_fee_product_active", "product_id", "is_active"),
        Index("ix_marketplace_fee_category_active", "seller_id", "marketplace", "category", "is_active"),
        Index("ix_marketplace_fee_effective", "effective_from", "effective_to"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=True)
    marketplace: Mapped[str] = mapped_column(String(120), nullable=False, default="Daraz Bangladesh")
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BDT")
    percentage_commission_rate: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False, default=Decimal("0.000000"))
    payment_fee_rate: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False, default=Decimal("0.000000"))
    fixed_per_order_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    fixed_per_unit_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    fulfilment_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    shipping_subsidy: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    other_variable_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    source: Mapped[str] = mapped_column(String(120), nullable=False, default="MANUAL")
    version: Mapped[str] = mapped_column(String(40), nullable=False, default="v1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship()
    product: Mapped["Product | None"] = relationship(back_populates="marketplace_fee_policies")
