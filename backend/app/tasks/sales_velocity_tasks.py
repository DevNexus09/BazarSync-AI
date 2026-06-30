from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.sales_velocity_service import SalesVelocityService

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="sales_velocity.calculate_daily_sales_velocity",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def calculate_daily_sales_velocity_task(
    self,
    *,
    batch_size: int = 500,
    as_of_date: str | None = None,
    window_days: int | None = None,
    calculation_version: str | None = None,
    seller_id: str | None = None,
    product_id: str | None = None,
) -> dict[str, int | str | None]:
    try:
        seller_uuid = UUID(seller_id) if seller_id else None
        product_uuid = UUID(product_id) if product_id else None
        as_of = date.fromisoformat(as_of_date) if as_of_date else None
    except ValueError as exc:
        logger.warning(
            "Invalid sales velocity task scope seller_id=%s product_id=%s as_of_date=%s",
            seller_id,
            product_id,
            as_of_date,
        )
        raise Ignore() from exc

    session = SessionLocal()
    try:
        result = SalesVelocityService(session, log=logger).calculate_for_batch(
            batch_size=batch_size,
            as_of_date=as_of,
            window_days=window_days,
            calculation_version=calculation_version,
            seller_id=seller_uuid,
            product_id=product_uuid,
        )
        logger.info(
            "Sales velocity task completed created=%s skipped=%s failed=%s seller_id=%s product_id=%s",
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
