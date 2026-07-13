from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product, ProductMarketplaceListing
    from app.models.seller import Seller


class ProductPriceHistorySource(str, Enum):
    PRODUCT_EDIT = "PRODUCT_EDIT"
    PRICING_RECOMMENDATION = "PRICING_RECOMMENDATION"
    COPILOT_PROPOSAL = "COPILOT_PROPOSAL"
    IMPORT = "IMPORT"
    UNKNOWN = "UNKNOWN"
    BASELINE_CURRENT_PRICE = "BASELINE_CURRENT_PRICE"


class ProductPriceHistory(Base):
    __tablename__ = "product_price_history"
    __table_args__ = (
        Index("ix_product_price_history_seller_id", "seller_id"),
        Index("ix_product_price_history_product_id", "product_id"),
        Index("ix_product_price_history_listing_id", "listing_id"),
        Index("ix_product_price_history_marketplace", "marketplace"),
        Index("ix_product_price_history_changed_at", "changed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    listing_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_marketplace_listings.id", ondelete="SET NULL"), nullable=True)
    marketplace: Mapped[str | None] = mapped_column(String(120), nullable=True)
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    new_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[ProductPriceHistorySource] = mapped_column(
        SAEnum(ProductPriceHistorySource, name="product_price_history_source"),
        nullable=False,
        default=ProductPriceHistorySource.UNKNOWN,
        server_default=ProductPriceHistorySource.UNKNOWN.value,
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="product_price_history")
    product: Mapped["Product"] = relationship(back_populates="price_history")
    listing: Mapped["ProductMarketplaceListing | None"] = relationship(back_populates="price_history")
