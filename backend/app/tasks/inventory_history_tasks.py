from __future__ import annotations

import logging
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.inventory_history_service import InventoryHistoryService

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="inventory_history.capture_daily_inventory_snapshots",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def capture_daily_inventory_snapshots_task(
    self,
    *,
    batch_size: int = 500,
    seller_id: str | None = None,
    product_id: str | None = None,
) -> dict[str, int | str | None]:
    try:
        seller_uuid = UUID(seller_id) if seller_id else None
        product_uuid = UUID(product_id) if product_id else None
    except ValueError as exc:
        logger.warning(
            "Invalid inventory snapshot scope seller_id=%s product_id=%s",
            seller_id,
            product_id,
        )
        raise Ignore() from exc

    session = SessionLocal()
    try:
        result = InventoryHistoryService(session, log=logger).capture_daily_snapshots(
            batch_size=batch_size,
            seller_id=seller_uuid,
            product_id=product_uuid,
        )
        logger.info(
            "Inventory snapshot task completed created=%s skipped=%s failed=%s seller_id=%s product_id=%s",
            result.created_count,
            result.skipped_count,
            result.failed_count,
            seller_id,
            product_id,
        )
        return {
            "created_count": result.created_count,
            "skipped_count": result.skipped_count,
            "failed_count": result.failed_count,
            "seller_id": seller_id,
            "product_id": product_id,
        }
    finally:
        session.close()
