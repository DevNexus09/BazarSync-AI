from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.inventory_stock_in import InventoryStockIn
from app.models.product import Product
from app.models.rag_memory import RagMemorySourceType
from app.schemas.inventory_stock_in import InventoryStockInCreate
from app.services.rag_index_outbox_service import RagIndexOutboxService


class InventoryStockInService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, *, seller_id: UUID, payload: InventoryStockInCreate) -> InventoryStockIn:
        product = self._db.execute(
            select(Product).where(Product.id == payload.product_id, Product.seller_id == seller_id)
        ).scalar_one_or_none()
        if product is None:
            raise ValueError("Product not found.")
        received_at = _ensure_utc(payload.received_at)
        if received_at > datetime.now(timezone.utc):
            raise ValueError("received_at cannot be in the future.")
        record = InventoryStockIn(
            seller_id=seller_id,
            product_id=payload.product_id,
            quantity=payload.quantity,
            received_at=received_at,
            unit_cost=payload.unit_cost,
            currency=payload.currency.upper() if payload.currency else None,
            source_reference=payload.source_reference,
            notes=payload.notes,
        )
        self._db.add(record)
        self._db.commit()
        self._db.refresh(record)
        RagIndexOutboxService(self._db).enqueue_upsert(
            seller_id=seller_id,
            source_type=RagMemorySourceType.INVENTORY_LIFECYCLE,
            source_id=str(record.id),
            product_id=record.product_id,
            source_updated_at=record.received_at,
        )
        self._db.commit()
        from app.tasks.dead_stock_workflow_tasks import enqueue_dead_stock_recalculation

        enqueue_dead_stock_recalculation(seller_id=seller_id, product_id=payload.product_id, reason="inventory_receipt")
        return record


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
