"""Background tasks for alerts."""

from __future__ import annotations

import logging

from app.core.celery_app import celery_app
from app.core.async_runner import run_async
from app.db.async_session import AsyncSessionLocal
from app.services.telegram.telegram_alert_service import (
    AlertDeliveryOutcome,
    TelegramAlertDeliveryService,
)

logger = logging.getLogger(__name__)


async def _deliver_alert(alert_id: str) -> AlertDeliveryOutcome:
    async with AsyncSessionLocal() as session:
        service = TelegramAlertDeliveryService(session, logger=logger)
        return await service.deliver_alert_by_id(alert_id)


@celery_app.task(name="alerts.send_telegram_alert")
def send_telegram_alert(alert_id: str) -> dict[str, str | None]:
    outcome = run_async(_deliver_alert(alert_id))
    return {
        "alert_id": outcome.alert_id,
        "status": outcome.status.value,
        "detail": outcome.detail,
    }
