from __future__ import annotations

import logging
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from app.core.async_runner import run_async
from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.telegram.inventory_alert_service import TelegramInventoryAlertService

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="telegram_inventory_alerts.generate_for_risk",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def generate_telegram_inventory_alerts_task(self, risk_assessment_id: str) -> dict[str, int | list[str]]:
    try:
        risk_uuid = UUID(risk_assessment_id)
    except ValueError as exc:
        logger.warning("Invalid telegram inventory alert risk_assessment_id=%s", risk_assessment_id)
        raise Ignore() from exc

    session = SessionLocal()
    try:
        result = TelegramInventoryAlertService(session, log=logger).generate_for_risk_assessment(risk_uuid)
        return {
            "created_count": result.created_count,
            "skipped_count": result.skipped_count,
            "alert_ids": result.alert_ids,
        }
    finally:
        session.close()


@celery_app.task(
    bind=True,
    name="telegram_inventory_alerts.deliver",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def deliver_telegram_inventory_alert_task(self, alert_id: str) -> dict[str, str | None]:
    try:
        alert_uuid = UUID(alert_id)
    except ValueError as exc:
        logger.warning("Invalid telegram inventory alert_id=%s", alert_id)
        raise Ignore() from exc

    session = SessionLocal()
    try:
        service = TelegramInventoryAlertService(session, log=logger)
        outcome = run_async(service.deliver_alert(alert_uuid))
        return {
            "alert_id": outcome.alert_id,
            "status": outcome.status.value,
            "detail": outcome.detail,
        }
    finally:
        session.close()


@celery_app.task(name="telegram_inventory_alerts.enqueue_due")
def enqueue_due_telegram_inventory_alerts_task(limit: int = 100) -> dict[str, int]:
    session = SessionLocal()
    try:
        alert_ids = TelegramInventoryAlertService(session, log=logger).enqueue_due_deliveries(limit=limit)
        for alert_id in alert_ids:
            deliver_telegram_inventory_alert_task.delay(alert_id)
        logger.info("telegram_inventory_alerts_due_enqueued count=%s", len(alert_ids))
        return {"enqueued_count": len(alert_ids)}
    finally:
        session.close()
