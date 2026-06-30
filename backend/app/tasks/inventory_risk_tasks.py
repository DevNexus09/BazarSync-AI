from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.inventory_risk_service import InventoryRiskService

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="inventory_risks.calculate_inventory_risks",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def calculate_inventory_risks_task(
    self,
    *,
    batch_size: int = 500,
    as_of_date: str | None = None,
    calculation_version: str | None = None,
    seller_id: str | None = None,
    product_id: str | None = None,
) -> dict[str, int | str | None]:
    try:
        seller_uuid = UUID(seller_id) if seller_id else None
        product_uuid = UUID(product_id) if product_id else None
        as_of = date.fromisoformat(as_of_date) if as_of_date else None
    except ValueError as exc:
        logger.warning("Invalid inventory risk task scope seller_id=%s product_id=%s as_of_date=%s", seller_id, product_id, as_of_date)
        raise Ignore() from exc

    session = SessionLocal()
    try:
        result = InventoryRiskService(session, log=logger).assess_for_batch(
            batch_size=batch_size,
            as_of_date=as_of,
            calculation_version=calculation_version,
            seller_id=seller_uuid,
            product_id=product_uuid,
        )
        from app.tasks.telegram_inventory_alert_tasks import generate_telegram_inventory_alerts_task

        for assessment_id in result.created_assessment_ids or []:
            generate_telegram_inventory_alerts_task.delay(assessment_id)
        return {
            "created_count": result.created_count,
            "skipped_count": result.skipped_count,
            "failed_count": result.failed_count,
            "insufficient_data_count": result.insufficient_data_count,
            "seller_id": seller_id,
            "product_id": product_id,
        }
    finally:
        session.close()
