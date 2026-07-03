from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class PricingObjective(str, Enum):
    MAXIMIZE_EXPECTED_PROFIT = "MAXIMIZE_EXPECTED_PROFIT"
    MAXIMIZE_REVENUE_WITH_MARGIN_FLOOR = "MAXIMIZE_REVENUE_WITH_MARGIN_FLOOR"
    PROTECT_INVENTORY = "PROTECT_INVENTORY"
    CLEAR_EXCESS_STOCK = "CLEAR_EXCESS_STOCK"


class PricingPolicy(Base):
    __tablename__ = "pricing_policies"
    __table_args__ = (
        CheckConstraint("minimum_margin_rate >= 0 AND minimum_margin_rate < 1", name="ck_pricing_policies_min_margin_rate"),
        CheckConstraint("minimum_unit_profit >= 0", name="ck_pricing_policies_min_unit_profit"),
        CheckConstraint("maximum_price_decrease_rate IS NULL OR (maximum_price_decrease_rate >= 0 AND maximum_price_decrease_rate < 1)", name="ck_pricing_policies_max_decrease_rate"),
        CheckConstraint("maximum_price_increase_rate IS NULL OR maximum_price_increase_rate >= 0", name="ck_pricing_policies_max_increase_rate"),
        CheckConstraint("minimum_allowed_price IS NULL OR minimum_allowed_price >= 0", name="ck_pricing_policies_min_price"),
        CheckConstraint("maximum_allowed_price IS NULL OR maximum_allowed_price >= 0", name="ck_pricing_policies_max_price"),
        CheckConstraint("minimum_allowed_price IS NULL OR maximum_allowed_price IS NULL OR minimum_allowed_price <= maximum_allowed_price", name="ck_pricing_policies_price_bounds"),
        CheckConstraint("price_increment > 0", name="ck_pricing_policies_price_increment"),
        CheckConstraint("recommendation_cooldown_hours >= 0", name="ck_pricing_policies_cooldown"),
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="ck_pricing_policies_effective_period"),
        UniqueConstraint("seller_id", "product_id", "marketplace", "effective_from", name="uq_pricing_policies_scope_start"),
        Index("ix_pricing_policies_product_marketplace_active", "product_id", "marketplace", "is_active"),
        Index("ix_pricing_policies_seller_marketplace_active", "seller_id", "marketplace", "is_active"),
        Index("ix_pricing_policies_effective", "effective_from", "effective_to"),
        Index(
            "uq_pricing_policies_active_product_marketplace",
            "seller_id",
            "product_id",
            "marketplace",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(120), nullable=False, default="Daraz Bangladesh")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BDT")
    minimum_margin_rate: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    minimum_unit_profit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    maximum_price_decrease_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    maximum_price_increase_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    minimum_allowed_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    maximum_allowed_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_increment: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("1.00"))
    recommendation_cooldown_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    objective: Mapped[PricingObjective] = mapped_column(
        SAEnum(PricingObjective, name="pricing_objective"),
        nullable=False,
        default=PricingObjective.MAXIMIZE_EXPECTED_PROFIT,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship()
    product: Mapped["Product"] = relationship(back_populates="pricing_policies")
