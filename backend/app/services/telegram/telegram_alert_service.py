from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.alert import Alert, AlertDeliveryStatus, AlertUrgencyLevel
from app.models.alert_delivery_log import AlertDeliveryLog
from app.services.telegram.telegram_connection_service import (
    TelegramConnectionService,
    TelegramConnectionSettings,
)
from app.services.telegram.telegram_formatter import AlertMessageContext
from app.services.telegram.telegram_service import DeliveryStatus, TelegramDeliveryResult, TelegramService
from app.websocket.socket_events import (
    AlertFailedEvent,
    AlertFailedPayload,
    AlertSentEvent,
    AlertSentPayload,
    AlertSnapshot,
)
from app.websocket.socket_manager import get_socket_emitter
from app.websocket.socket_rooms import seller_room


class AlertDeliveryError(Exception):
    """Base error for alert delivery failures."""


class AlertNotFoundError(AlertDeliveryError):
    """Raised when an alert cannot be located."""


@dataclass(frozen=True)
class AlertDeliveryOutcome:
    alert_id: str
    status: AlertDeliveryStatus
    detail: str | None = None
    telegram_message_id: str | None = None
    telegram_chat_id: str | None = None
    delivered_at: datetime | None = None


class TelegramAlertDeliveryService:
    """Routes alerts to seller-specific Telegram chats with cooldown + logging."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: TelegramConnectionSettings | None = None,
        telegram_service: TelegramService | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or TelegramConnectionSettings()
        self._telegram = telegram_service or TelegramService(logger=logger)
        self._logger = logger or logging.getLogger(__name__)
        self._connections = TelegramConnectionService(
            session,
            settings=self._settings,
            logger=self._logger,
        )

    async def deliver_alert_by_id(self, alert_id: str | UUID) -> AlertDeliveryOutcome:
        alert = await self._get_alert(alert_id)
        if not alert:
            raise AlertNotFoundError("Alert not found.")
        return await self.deliver_alert(alert)

    async def deliver_alert(self, alert: Alert) -> AlertDeliveryOutcome:
        connection = await self._connections.get_status(str(alert.seller_id))
        if not connection or not connection.is_connected or not connection.telegram_chat_id:
            return await self._record_failure(
                alert,
                detail="seller_not_connected",
                chat_id=None,
            )

        if await self._is_in_cooldown(alert):
            return await self._record_duplicate(alert, detail="cooldown_active")

        context = self._build_message_context(alert)
        result = await self._telegram.send_alert_message(
            context,
            chat_id=connection.telegram_chat_id,
            idempotency_key=f"alert:{alert.id}",
        )
        return await self._apply_delivery_result(alert, connection.telegram_chat_id, result)

    async def _get_alert(self, alert_id: str | UUID) -> Alert | None:
        statement = (
            select(Alert)
            .where(Alert.id == alert_id)
            .options(selectinload(Alert.product))
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def _is_in_cooldown(self, alert: Alert) -> bool:
        cooldown = self._settings.alert_cooldown_seconds
        if cooldown <= 0:
            return False
        cutoff = self._now() - timedelta(seconds=cooldown)
        statement = (
            select(AlertDeliveryLog.sent_at)
            .join(Alert, AlertDeliveryLog.alert_id == Alert.id)
            .where(
                AlertDeliveryLog.seller_id == alert.seller_id,
                AlertDeliveryLog.delivery_status == AlertDeliveryStatus.delivered,
                AlertDeliveryLog.sent_at.is_not(None),
                AlertDeliveryLog.sent_at >= cutoff,
                Alert.action_type == alert.action_type,
                Alert.product_id == alert.product_id,
                Alert.alert_type == alert.alert_type,
            )
            .order_by(AlertDeliveryLog.sent_at.desc())
            .limit(1)
        )
        last_sent = await self._session.scalar(statement)
        return last_sent is not None

    async def _apply_delivery_result(
        self,
        alert: Alert,
        chat_id: str,
        result: TelegramDeliveryResult,
    ) -> AlertDeliveryOutcome:
        status = self._map_delivery_status(result.status)
        now = result.timestamp
        if status is AlertDeliveryStatus.delivered:
            alert.delivery_status = AlertDeliveryStatus.delivered
            alert.telegram_chat_id = chat_id
            alert.telegram_message_id = str(result.message_id) if result.message_id else None
            alert.delivery_error = None
            alert.delivered_at = now
        elif status is AlertDeliveryStatus.duplicate:
            alert.delivery_status = AlertDeliveryStatus.duplicate
            alert.telegram_chat_id = chat_id
            alert.delivery_error = result.detail or "duplicate_alert_skipped"
            alert.telegram_message_id = None
            alert.delivered_at = None
        else:
            alert.delivery_status = AlertDeliveryStatus.failed
            alert.telegram_chat_id = chat_id
            alert.delivery_error = result.detail
            alert.telegram_message_id = None
            alert.delivered_at = None

        if status is AlertDeliveryStatus.delivered:
            connection = await self._connections.get_status(str(alert.seller_id))
            if connection:
                connection.last_alert_sent_at = now

        log = AlertDeliveryLog(
            seller_id=alert.seller_id,
            alert_id=alert.id,
            telegram_chat_id=chat_id,
            delivery_status=status,
            error_message=result.detail if status is not AlertDeliveryStatus.delivered else None,
            sent_at=now if status is AlertDeliveryStatus.delivered else None,
        )
        self._session.add(log)
        await self._session.commit()

        if status is AlertDeliveryStatus.delivered:
            await self._emit_alert_sent(alert)
        else:
            await self._emit_alert_failed(alert, status, result.detail, chat_id)

        self._logger.info(
            "telegram_alert_delivery alert_id=%s status=%s chat_id=%s",
            alert.id,
            status.value,
            chat_id,
        )
        return AlertDeliveryOutcome(
            alert_id=str(alert.id),
            status=status,
            detail=result.detail,
            telegram_message_id=str(result.message_id) if result.message_id else None,
            telegram_chat_id=chat_id,
            delivered_at=now if status is AlertDeliveryStatus.delivered else None,
        )

    async def _record_failure(
        self,
        alert: Alert,
        *,
        detail: str,
        chat_id: str | None,
    ) -> AlertDeliveryOutcome:
        alert.delivery_status = AlertDeliveryStatus.failed
        alert.delivery_error = detail
        alert.telegram_chat_id = chat_id
        alert.telegram_message_id = None
        alert.delivered_at = None
        log = AlertDeliveryLog(
            seller_id=alert.seller_id,
            alert_id=alert.id,
            telegram_chat_id=chat_id,
            delivery_status=AlertDeliveryStatus.failed,
            error_message=detail,
        )
        self._session.add(log)
        await self._session.commit()
        await self._emit_alert_failed(alert, AlertDeliveryStatus.failed, detail, chat_id)
        return AlertDeliveryOutcome(
            alert_id=str(alert.id),
            status=AlertDeliveryStatus.failed,
            detail=detail,
            telegram_chat_id=chat_id,
        )

    async def _record_duplicate(
        self,
        alert: Alert,
        *,
        detail: str,
    ) -> AlertDeliveryOutcome:
        alert.delivery_status = AlertDeliveryStatus.duplicate
        alert.delivery_error = detail
        alert.telegram_message_id = None
        alert.delivered_at = None
        log = AlertDeliveryLog(
            seller_id=alert.seller_id,
            alert_id=alert.id,
            telegram_chat_id=alert.telegram_chat_id,
            delivery_status=AlertDeliveryStatus.duplicate,
            error_message=detail,
        )
        self._session.add(log)
        await self._session.commit()
        await self._emit_alert_failed(
            alert, AlertDeliveryStatus.duplicate, detail, alert.telegram_chat_id
        )
        return AlertDeliveryOutcome(
            alert_id=str(alert.id),
            status=AlertDeliveryStatus.duplicate,
            detail=detail,
            telegram_chat_id=alert.telegram_chat_id,
        )

    def _build_message_context(self, alert: Alert) -> AlertMessageContext:
        payload = alert.payload or {}
        return AlertMessageContext(
            product_name=(
                alert.product.title if alert.product else str(alert.product_id)
            ),
            action=self._format_action(alert.action_type),
            suggested_price_min=_optional_float(
                payload.get("suggested_price_min")
                or payload.get("recommended_price_min")
                or payload.get("recommended_price")
            ),
            suggested_price_max=_optional_float(
                payload.get("suggested_price_max")
                or payload.get("recommended_price_max")
            ),
            competitor_insight=_normalize_text(
                payload.get("reasoning_summary")
                or payload.get("reasoning")
                or payload.get("triggered_rules")
            ),
            opportunity=_normalize_text(
                payload.get("market_opportunity")
                or payload.get("opportunity")
                or payload.get("reasoning_summary")
            ),
            confidence=self._format_confidence(alert.confidence),
            revenue_opportunity=_optional_float(payload.get("revenue_opportunity")),
            product_id=str(alert.product_id),
            recommendation_id=str(alert.recommendation_id)
            if alert.recommendation_id
            else None,
            alert_type=str(alert.alert_type),
        )

    async def _emit_alert_sent(self, alert: Alert) -> None:
        emitter = self._resolve_emitter()
        if not emitter:
            return
        snapshot = self._build_alert_snapshot(alert)
        event = AlertSentEvent(
            payload=AlertSentPayload(alert=snapshot),
            seller_id=alert.seller_id,
            product_id=alert.product_id,
        )
        await emitter.emit_event(event, rooms=[seller_room(str(alert.seller_id))])

    async def _emit_alert_failed(
        self,
        alert: Alert,
        status: AlertDeliveryStatus,
        reason: str | None,
        chat_id: str | None,
    ) -> None:
        emitter = self._resolve_emitter()
        if not emitter:
            return
        event = AlertFailedEvent(
            payload=AlertFailedPayload(
                alert_id=alert.id,
                status=status.value,
                reason=reason,
                telegram_chat_id=chat_id,
            ),
            seller_id=alert.seller_id,
            product_id=alert.product_id,
        )
        await emitter.emit_event(event, rooms=[seller_room(str(alert.seller_id))])

    def _build_alert_snapshot(self, alert: Alert) -> AlertSnapshot:
        product_title = alert.product.title if alert.product else None
        urgency_level = self._format_urgency(alert.urgency_level)
        return AlertSnapshot(
            id=alert.id,
            title=f"{self._format_label(alert.action_type).title()} for "
            f"{product_title or 'product'}",
            message=f"{self._format_label(alert.alert_type)} alert, "
            f"{self._format_label(urgency_level)} urgency.",
            severity=self._severity_from_urgency(urgency_level),
            status="new",
            category=self._category_from_action(alert.action_type, alert.alert_type),
            channel="telegram",
            product=product_title,
            competitor=None,
            urgency_score=self._urgency_score_from_level(urgency_level),
            created_at=alert.created_at,
        )

    def _map_delivery_status(self, status: DeliveryStatus) -> AlertDeliveryStatus:
        if status is DeliveryStatus.duplicate:
            return AlertDeliveryStatus.duplicate
        if status is DeliveryStatus.delivered:
            return AlertDeliveryStatus.delivered
        return AlertDeliveryStatus.failed

    def _resolve_emitter(self):
        try:
            return get_socket_emitter()
        except RuntimeError:
            self._logger.debug("socket_emitter_unavailable")
            return None

    @staticmethod
    def _format_action(value: Any) -> str:
        return TelegramAlertDeliveryService._format_label(value).replace("_", " ").title()

    @staticmethod
    def _format_confidence(value: Any) -> str | None:
        if isinstance(value, Enum):
            return value.value
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _format_urgency(value: Any) -> str:
        if isinstance(value, Enum):
            return value.value
        if value is None:
            return AlertUrgencyLevel.MEDIUM.value
        return str(value)

    @staticmethod
    def _format_label(value: Any) -> str:
        if value is None:
            return "alert"
        if isinstance(value, Enum):
            value = value.value
        return str(value).replace("_", " ").lower()

    @staticmethod
    def _severity_from_urgency(level: str) -> str:
        normalized = level.upper()
        if normalized == "CRITICAL":
            return "critical"
        if normalized == "HIGH":
            return "high"
        if normalized == "MEDIUM":
            return "medium"
        return "low"

    @staticmethod
    def _urgency_score_from_level(level: str) -> int:
        normalized = level.upper()
        if normalized == "CRITICAL":
            return 90
        if normalized == "HIGH":
            return 75
        if normalized == "MEDIUM":
            return 55
        return 30

    @staticmethod
    def _category_from_action(action: Any, alert_type: Any) -> str:
        action_value = (
            action.value if isinstance(action, Enum) else str(action or "")
        ).upper()
        if action_value in {"STOCK_WARNING", "REORDER"}:
            return "stock_risk"
        if action_value.startswith("PRICE"):
            return "price_war"
        if action_value == "OPPORTUNITY_CAPTURE":
            return "opportunity"
        if "system" in str(alert_type or "").lower():
            return "system"
        return "competitor_move"

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    return str(value)
