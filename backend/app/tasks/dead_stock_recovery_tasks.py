from __future__ import annotations

import logging
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.dead_stock_recovery_service import DeadStockRecoveryService

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="dead_stock.generate_recovery_recommendation",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def generate_dead_stock_recovery_recommendation_task(
    self,
    *,
    seller_id: str,
    product_id: str,
) -> dict[str, str | bool]:
    del self
    try:
        seller_uuid = UUID(seller_id)
        product_uuid = UUID(product_id)
    except ValueError as exc:
        logger.warning("invalid_dead_stock_recovery_scope seller_id=%s product_id=%s", seller_id, product_id)
        raise Ignore() from exc

    session = SessionLocal()
    try:
        recommendation, created = DeadStockRecoveryService(session).generate_for_product(
            seller_id=seller_uuid,
            product_id=product_uuid,
        )
        return {
            "recommendation_id": str(recommendation.id),
            "seller_id": seller_id,
            "product_id": product_id,
            "created": created,
        }
    finally:
        session.close()
