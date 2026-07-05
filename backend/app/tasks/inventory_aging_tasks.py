from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.inventory_aging_service import InventoryAgingService

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="inventory_aging.calculate_inventory_aging",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def calculate_inventory_aging_task(
    self,
    *,
    batch_size: int = 500,
    as_of_date: str | None = None,
    seller_id: str | None = None,
    product_id: str | None = None,
) -> dict[str, int | str | None]:
    try:
        seller_uuid = UUID(seller_id) if seller_id else None
        product_uuid = UUID(product_id) if product_id else None
        as_of = date.fromisoformat(as_of_date) if as_of_date else None
    except ValueError as exc:
        logger.warning(
            "invalid_inventory_aging_scope seller_id=%s product_id=%s as_of_date=%s",
            seller_id,
            product_id,
            as_of_date,
        )
        raise Ignore() from exc

    session = SessionLocal()
    try:
        result = InventoryAgingService(session, log=logger).calculate_batch(
            batch_size=batch_size,
            as_of_date=as_of,
            seller_id=seller_uuid,
            product_id=product_uuid,
        )
        logger.info(
            "inventory_aging_task_completed calculated=%s estimated=%s unavailable=%s skipped=%s failed=%s seller_id=%s product_id=%s",
            result.calculated_count,
            result.estimated_count,
            result.unavailable_count,
            result.skipped_count,
            result.failed_count,
            seller_id,
            product_id,
        )
        return {
            "calculated_count": result.calculated_count,
            "estimated_count": result.estimated_count,
            "unavailable_count": result.unavailable_count,
            "skipped_count": result.skipped_count,
            "failed_count": result.failed_count,
            "seller_id": seller_id,
            "product_id": product_id,
            "as_of_date": as_of_date,
        }
    finally:
        session.close()


@celery_app.task(
    bind=True,
    name="inventory_aging.backfill_baseline",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def backfill_inventory_aging_baseline_task(
    self,
    *,
    batch_size: int = 500,
    as_of_date: str | None = None,
    seller_id: str | None = None,
    product_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, int | str | bool | None]:
    try:
        seller_uuid = UUID(seller_id) if seller_id else None
        product_uuid = UUID(product_id) if product_id else None
        as_of = date.fromisoformat(as_of_date) if as_of_date else None
    except ValueError as exc:
        logger.warning(
            "invalid_inventory_aging_backfill_scope seller_id=%s product_id=%s as_of_date=%s",
            seller_id,
            product_id,
            as_of_date,
        )
        raise Ignore() from exc

    session = SessionLocal()
    try:
        result = InventoryAgingService(session, log=logger).backfill_baseline(
            batch_size=batch_size,
            as_of_date=as_of,
            seller_id=seller_uuid,
            product_id=product_uuid,
            dry_run=dry_run,
        )
        logger.info(
            "inventory_aging_backfill_completed calculated=%s estimated=%s unavailable=%s skipped=%s failed=%s dry_run_count=%s seller_id=%s product_id=%s",
            result.calculated_count,
            result.estimated_count,
            result.unavailable_count,
            result.skipped_count,
            result.failed_count,
            result.dry_run_count,
            seller_id,
            product_id,
        )
        return {
            "calculated_count": result.calculated_count,
            "estimated_count": result.estimated_count,
            "unavailable_count": result.unavailable_count,
            "skipped_count": result.skipped_count,
            "failed_count": result.failed_count,
            "dry_run_count": result.dry_run_count,
            "dry_run": dry_run,
            "seller_id": seller_id,
            "product_id": product_id,
            "as_of_date": as_of_date,
        }
    finally:
        session.close()
