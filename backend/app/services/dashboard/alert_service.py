from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.repositories.alert_repository import AlertRepository
from app.repositories.query_utils import PaginationParams, SortDirection, build_pagination_meta
from app.schemas.dashboard.alert_schema import AlertListResponse, AlertRecord
from app.services.dashboard.events import DashboardEventEmitter, NoopEventEmitter
from app.services.dashboard.exceptions import DashboardDatabaseError


class AlertDashboardService:
    def __init__(
        self,
        repository: AlertRepository,
        *,
        logger: logging.Logger | None = None,
        event_emitter: DashboardEventEmitter | None = None,
    ) -> None:
        self._repo = repository
        self._logger = logger or logging.getLogger(__name__)
        self._events = event_emitter or NoopEventEmitter()

    async def list_alerts(
        self,
        *,
        seller_id: str | None,
        product_id: str | None,
        urgency_level: str | None,
        action_type: str | None,
        delivery_status: str | None,
        is_read: bool | None,
        date_from: Any,
        date_to: Any,
        sort_by: str,
        sort_direction: SortDirection,
        pagination: PaginationParams,
    ) -> AlertListResponse:
        start = time.monotonic()
        try:
            rows, total = await self._repo.list_alerts(
                seller_id=seller_id,
                product_id=product_id,
                urgency_level=urgency_level,
                action_type=action_type,
                delivery_status=delivery_status,
                is_read=is_read,
                date_from=date_from,
                date_to=date_to,
                sort_by=sort_by,
                sort_direction=sort_direction,
                pagination=pagination,
            )
        except SQLAlchemyError as exc:
            raise DashboardDatabaseError("Failed to load alerts.") from exc
        items = [self._to_record(row) for row in rows]
        meta = build_pagination_meta(total, pagination)
        duration_ms = int((time.monotonic() - start) * 1000)
        self._logger.info(
            "dashboard_alerts_list total=%s duration_ms=%s seller_id=%s product_id=%s status=%s page=%s page_size=%s",
            total,
            duration_ms,
            seller_id,
            product_id,
            delivery_status,
            pagination.page,
            pagination.page_size,
        )
        return AlertListResponse(items=items, meta=meta)

    def _to_record(self, row: Any) -> AlertRecord:
        reference = None
        if row.get("telegram_chat_id") or row.get("telegram_message_id"):
            reference = f"chat:{row.get('telegram_chat_id')} msg:{row.get('telegram_message_id')}"
        return AlertRecord(
            alert_id=str(row["alert_id"]),
            product_id=str(row["product_id"]),
            product_title=row["product_title"],
            alert_type=str(row["alert_type"]),
            urgency_level=str(row["urgency_level"]),
            action_type=str(row["action_type"]),
            confidence=str(row["confidence"]),
            delivery_status=str(row["delivery_status"]),
            delivery_timestamp=row.get("delivered_at"),
            telegram_reference=reference,
            is_read=row.get("read_at") is not None,
            read_at=row.get("read_at"),
            created_at=row.get("created_at"),
        )
