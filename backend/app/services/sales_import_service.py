from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.sales_record import SalesRecord, SalesRecordStatus
from app.schemas.sales_import import SalesImportRequest, SalesImportResponse

VALID_COUNTING_STATUSES = {SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED}


class SalesImportService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def import_records(self, *, seller_id: UUID, payload: SalesImportRequest) -> SalesImportResponse:
        product_ids = {record.product_id for record in payload.records}
        owned = set(
            self._db.execute(
                select(Product.id).where(Product.seller_id == seller_id, Product.id.in_(product_ids))
            ).scalars().all()
        )
        if owned != product_ids:
            raise ValueError("One or more products were not found.")

        imported = skipped = valid = excluded = 0
        affected_products: set[UUID] = set()
        for item in payload.records:
            sold_at = _ensure_utc(item.sold_at)
            if sold_at > datetime.now(timezone.utc):
                raise ValueError("sold_at cannot be in the future.")
            existing = self._db.execute(
                select(SalesRecord).where(
                    SalesRecord.seller_id == seller_id,
                    SalesRecord.source_reference == item.source_reference,
                )
            ).scalar_one_or_none()
            if existing:
                skipped += 1
                continue
            record = SalesRecord(
                seller_id=seller_id,
                product_id=item.product_id,
                source_reference=item.source_reference,
                status=item.status,
                sold_at=sold_at,
                quantity_sold=item.quantity,
                returned_units=0,
                refunded_restocked_units=0,
                is_test_order=item.is_test_order,
            )
            self._db.add(record)
            imported += 1
            affected_products.add(item.product_id)
            if item.status in VALID_COUNTING_STATUSES and not item.is_test_order:
                valid += 1
            else:
                excluded += 1
        self._db.commit()
        from app.tasks.dead_stock_workflow_tasks import enqueue_dead_stock_recalculation

        for product_id in affected_products:
            enqueue_dead_stock_recalculation(seller_id=seller_id, product_id=product_id, reason="completed_sale")
        return SalesImportResponse(
            imported_count=imported,
            skipped_duplicate_count=skipped,
            valid_sales_count=valid,
            excluded_sales_count=excluded,
        )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
