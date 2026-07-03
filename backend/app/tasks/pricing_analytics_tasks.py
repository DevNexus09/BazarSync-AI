from __future__ import annotations

import hashlib
import logging
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.pricing_analytics_service import PricingAnalyticsService

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="pricing_analytics.calculate",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def calculate_pricing_analytics_task(
    self,
    *,
    seller_id: str | None = None,
    product_id: str | None = None,
    batch_size: int = 500,
) -> dict[str, int | str | None]:
    try:
        seller_uuid = UUID(seller_id) if seller_id else None
        product_uuid = UUID(product_id) if product_id else None
    except ValueError as exc:
        logger.warning("pricing_analytics_invalid_scope seller_id=%s product_id=%s", seller_id, product_id)
        raise Ignore() from exc

    session = SessionLocal()
    lock_key = f"pricing-analytics:{seller_uuid or 'all'}:{product_uuid or 'all'}"
    try:
        if not _try_advisory_lock(session, lock_key):
            logger.info("pricing_analytics_lock_contention seller_id=%s product_id=%s", seller_id, product_id)
            return {
                "seller_id": seller_id,
                "product_id": product_id,
                "processed_count": 0,
                "snapshot_count": 0,
                "failed_count": 0,
                "skipped_reason": "locked",
            }
        result = PricingAnalyticsService(session).generate_batch(
            seller_id=seller_uuid,
            product_id=product_uuid,
            batch_size=batch_size,
        )
        logger.info(
            "pricing_analytics_calculation_completed seller_id=%s product_id=%s processed=%s snapshots=%s failed=%s",
            seller_id,
            product_id,
            result["processed_count"],
            result["snapshot_count"],
            result["failed_count"],
        )
        return {**result, "seller_id": seller_id, "product_id": product_id, "skipped_reason": None}
    finally:
        session.close()


def _try_advisory_lock(session, key: str) -> bool:
    lock_id = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:15], 16)
    try:
        return bool(session.execute(select(func.pg_try_advisory_xact_lock(lock_id))).scalar_one())
    except SQLAlchemyError:
        session.rollback()
        return True
