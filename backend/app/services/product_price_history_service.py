from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory, ProductPriceHistorySource
from app.models.rag_memory import RagMemorySourceType
from app.services.rag_index_outbox_service import RagIndexOutboxService


class ProductPriceHistoryService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def record_price_change(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        old_price: Decimal | None,
        new_price: Decimal,
        currency: str = "BDT",
        listing_id: UUID | None = None,
        marketplace: str | None = None,
        reason: str | None = None,
        source: ProductPriceHistorySource = ProductPriceHistorySource.PRODUCT_EDIT,
        changed_by_user_id: UUID | None = None,
        changed_at: datetime | None = None,
    ) -> ProductPriceHistory:
        row = ProductPriceHistory(
            seller_id=seller_id,
            product_id=product_id,
            listing_id=listing_id,
            marketplace=marketplace,
            old_price=old_price,
            new_price=new_price,
            currency=currency,
            reason=reason,
            source=source,
            changed_by_user_id=changed_by_user_id,
            changed_at=changed_at or datetime.now(timezone.utc),
        )
        self._db.add(row)
        self._db.flush()
        RagIndexOutboxService(self._db).enqueue_upsert(
            seller_id=seller_id,
            source_type=RagMemorySourceType.SELLER_PRICE_HISTORY,
            source_id=str(row.id),
            product_id=product_id,
            source_updated_at=row.changed_at,
        )
        return row

    def create_baseline_current_price(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        currency: str = "BDT",
        reason: str | None = None,
        changed_by_user_id: UUID | None = None,
    ) -> ProductPriceHistory:
        product = self._db.execute(select(Product).where(Product.seller_id == seller_id, Product.id == product_id)).scalar_one_or_none()
        if product is None:
            raise PermissionError("Product does not belong to the authenticated seller.")
        return self.record_price_change(
            seller_id=seller_id,
            product_id=product_id,
            old_price=None,
            new_price=Decimal(product.selling_price),
            currency=currency,
            reason=reason or "Baseline snapshot of current product price; not a historical change.",
            source=ProductPriceHistorySource.BASELINE_CURRENT_PRICE,
            changed_by_user_id=changed_by_user_id,
        )
