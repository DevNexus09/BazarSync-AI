from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product, ProductMarketplaceListing
from app.models.sales_data_coverage import SalesDataCoverage, SalesDataCompletenessStatus
from app.models.sales_record import SalesRecord, SalesRecordPriceSource, SalesRecordStatus
from app.models.rag_memory import RagMemorySourceType
from app.schemas.sales_import import SalesImportRequest, SalesImportResponse
from app.services.rag_index_outbox_service import RagIndexOutboxService

VALID_COUNTING_STATUSES = {SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED}


class SalesImportService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def import_records(self, *, seller_id: UUID, payload: SalesImportRequest) -> SalesImportResponse:
        if payload.coverage_start_date and payload.coverage_end_date and payload.coverage_end_date < payload.coverage_start_date:
            raise ValueError("coverage_end_date cannot be before coverage_start_date.")
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
        imported_sold_dates = []
        imported_records: list[SalesRecord] = []
        for item in payload.records:
            sold_at = _ensure_utc(item.sold_at)
            if sold_at > datetime.now(timezone.utc):
                raise ValueError("sold_at cannot be in the future.")
            if item.source_reference:
                existing = self._db.execute(
                    select(SalesRecord).where(
                        SalesRecord.seller_id == seller_id,
                        SalesRecord.source_reference == item.source_reference,
                    )
                ).scalar_one_or_none()
                if existing:
                    skipped += 1
                    continue
            if item.marketplace_listing_id:
                listing_exists = self._db.execute(
                    select(ProductMarketplaceListing.id).where(
                        ProductMarketplaceListing.seller_id == seller_id,
                        ProductMarketplaceListing.product_id == item.product_id,
                        ProductMarketplaceListing.marketplace_listing_id == item.marketplace_listing_id,
                        ProductMarketplaceListing.archived_at.is_(None),
                    )
                ).first()
                if listing_exists is None:
                    raise ValueError("marketplace_listing_id was not found for this seller product.")
            line_total = _line_total(unit_price=item.unit_price, quantity=item.quantity)
            record = SalesRecord(
                seller_id=seller_id,
                product_id=item.product_id,
                source_reference=item.source_reference,
                status=item.status,
                sold_at=sold_at,
                quantity_sold=item.quantity,
                unit_price=item.unit_price,
                line_total=line_total,
                currency=item.currency,
                marketplace_listing_id=item.marketplace_listing_id,
                price_source=SalesRecordPriceSource.IMPORTED_TRANSACTION if item.unit_price is not None else SalesRecordPriceSource.UNKNOWN,
                returned_units=0,
                refunded_restocked_units=0,
                is_test_order=item.is_test_order,
            )
            self._db.add(record)
            imported_records.append(record)
            imported += 1
            affected_products.add(item.product_id)
            imported_sold_dates.append(sold_at.date())
            if item.status in VALID_COUNTING_STATUSES and not item.is_test_order:
                valid += 1
            else:
                excluded += 1
        if imported:
            self._db.add(
                SalesDataCoverage(
                    seller_id=seller_id,
                    marketplace=payload.marketplace,
                    product_id=next(iter(product_ids)) if len(product_ids) == 1 else None,
                    source=payload.source,
                    coverage_start_date=payload.coverage_start_date or min(imported_sold_dates),
                    coverage_end_date=payload.coverage_end_date or max(imported_sold_dates),
                    completeness_status=payload.completeness_status or SalesDataCompletenessStatus.UNKNOWN,
                    imported_record_count=imported,
                    valid_sales_count=valid,
                    invalid_or_excluded_count=excluded,
                    last_imported_at=datetime.now(timezone.utc),
                )
            )
            self._db.flush()
            outbox = RagIndexOutboxService(self._db)
            for record in imported_records:
                outbox.enqueue_upsert(
                    seller_id=seller_id,
                    source_type=RagMemorySourceType.SALES_HISTORY,
                    source_id=str(record.id),
                    product_id=record.product_id,
                    source_updated_at=record.sold_at,
                )
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


def _line_total(*, unit_price: Decimal | None, quantity: int) -> Decimal | None:
    if unit_price is None:
        return None
    return unit_price * Decimal(quantity)
