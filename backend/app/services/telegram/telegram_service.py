from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field
from telegram.constants import ParseMode

from app.core.async_runner import run_async as run_async_core
from app.services.telegram.telegram_client import (
    TelegramApiError,
    TelegramClient,
    TelegramClientError,
    TelegramInvalidChatError,
    TelegramMessagePayload,
    TelegramNetworkError,
    TelegramPayloadError,
    TelegramRateLimitError,
    TelegramSettings,
    TelegramTimeoutError,
    TelegramUnauthorizedError,
)
from app.services.telegram.telegram_formatter import AlertMessageContext, format_alert_message
from app.services.telegram.telegram_templates import DEFAULT_ALERT_TEMPLATE_KEY, get_template
from app.services.dashboard.events import DashboardEvent
from app.websocket.socket_manager import socket_manager

EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]


class DeliveryStatus(str, Enum):
    delivered = "delivered"
    failed = "failed"
    duplicate = "duplicate"


class TelegramSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chat_id: int | str
    text: str
    parse_mode: str | None = None
    disable_web_page_preview: bool = True
    alert_type: str | None = None
    product_id: str | None = None
    recommendation_id: str | None = None
    idempotency_key: str | None = None


class TelegramDeliveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    status: DeliveryStatus
    detail: str | None = None
    message_id: int | None = None
    chat_id: int | str | None = None
    response_time_ms: int | None = None
    retry_count: int = 0
    telegram_response: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    alert_type: str | None = None
    product_id: str | None = None
    recommendation_id: str | None = None
    idempotency_key: str | None = None


class IdempotencyStore(Protocol):
    async def is_duplicate(self, key: str) -> bool: ...

    async def record(self, key: str, ttl_seconds: int) -> None: ...


class InMemoryIdempotencyStore:
    """Process-local idempotency store for duplicate prevention."""

    def __init__(self) -> None:
        self._entries: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def is_duplicate(self, key: str) -> bool:
        async with self._lock:
            self._prune()
            return key in self._entries

    async def record(self, key: str, ttl_seconds: int) -> None:
        async with self._lock:
            self._entries[key] = time.monotonic() + ttl_seconds

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [key for key, expires_at in self._entries.items() if expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)


class TelegramService:
    """Orchestrates formatting, idempotency, retries, and delivery logging."""

    def __init__(
        self,
        settings: TelegramSettings | None = None,
        *,
        client: TelegramClient | None = None,
        idempotency_store: IdempotencyStore | None = None,
        logger: logging.Logger | None = None,
        event_emitter: EventEmitter | None = None,
    ) -> None:
        self._settings = settings or TelegramSettings()
        self._logger = logger or logging.getLogger(__name__)
        self._client = client or TelegramClient(self._settings, logger=self._logger)
        self._idempotency_store = idempotency_store or InMemoryIdempotencyStore()
        self._event_emitter = event_emitter or socket_manager.emit

    async def send_text_message(
        self,
        text: str,
        *,
        chat_id: int | str | None = None,
        parse_mode: str | None = None,
        prevent_duplicate: bool = False,
        idempotency_key: str | None = None,
        alert_type: str | None = None,
        product_id: str | None = None,
        recommendation_id: str | None = None,
    ) -> TelegramDeliveryResult:
        resolved_chat_id = self._resolve_chat_id(chat_id)
        request = TelegramSendRequest(
            chat_id=resolved_chat_id,
            text=text,
            parse_mode=parse_mode,
            alert_type=alert_type,
            product_id=product_id,
            recommendation_id=recommendation_id,
            idempotency_key=idempotency_key,
        )
        return await self.retry_failed_delivery(request, prevent_duplicate=prevent_duplicate)

    async def send_alert_message(
        self,
        alert: AlertMessageContext,
        *,
        chat_id: int | str | None = None,
        template_key: str | None = DEFAULT_ALERT_TEMPLATE_KEY,
        idempotency_key: str | None = None,
    ) -> TelegramDeliveryResult:
        template = get_template(template_key)
        message = format_alert_message(alert, template)
        return await self.send_text_message(
            message,
            chat_id=chat_id,
            parse_mode=ParseMode.MARKDOWN_V2,
            prevent_duplicate=True,
            idempotency_key=idempotency_key,
            alert_type=alert.alert_type,
            product_id=alert.product_id,
            recommendation_id=alert.recommendation_id,
        )

    async def send_bulk_alerts(
        self,
        alerts: Sequence[AlertMessageContext],
        *,
        chat_id: int | str | None = None,
        template_key: str | None = DEFAULT_ALERT_TEMPLATE_KEY,
        concurrency_limit: int = 10,
    ) -> list[TelegramDeliveryResult]:
        semaphore = asyncio.Semaphore(concurrency_limit)

        async def send_one(alert: AlertMessageContext) -> TelegramDeliveryResult:
            async with semaphore:
                return await self.send_alert_message(
                    alert,
                    chat_id=chat_id,
                    template_key=template_key,
                )

        tasks = [send_one(alert) for alert in alerts]
        return list(await asyncio.gather(*tasks))

    async def retry_failed_delivery(
        self,
        request: TelegramSendRequest,
        *,
        prevent_duplicate: bool = False,
        max_retries: int | None = None,
        idempotency_ttl_seconds: int = 3600,
    ) -> TelegramDeliveryResult:
        if prevent_duplicate:
            idempotency_key = request.idempotency_key or self._build_idempotency_key(request)
            request = request.model_copy(update={"idempotency_key": idempotency_key})
            if await self._idempotency_store.is_duplicate(idempotency_key):
                result = TelegramDeliveryResult(
                    success=True,
                    status=DeliveryStatus.duplicate,
                    detail="duplicate_alert_skipped",
                    chat_id=request.chat_id,
                    alert_type=request.alert_type,
                    product_id=request.product_id,
                    recommendation_id=request.recommendation_id,
                    idempotency_key=idempotency_key,
                )
                self.structured_delivery_logging(result)
                return result

        retries = max_retries if max_retries is not None else self._settings.max_retries
        retry_count = 0

        while True:
            start_time = time.monotonic()
            try:
                payload = await self._send_once(request)
                response_time_ms = int((time.monotonic() - start_time) * 1000)
                result = TelegramDeliveryResult(
                    success=True,
                    status=DeliveryStatus.delivered,
                    message_id=payload.message_id,
                    chat_id=payload.chat_id,
                    response_time_ms=response_time_ms,
                    retry_count=retry_count,
                    telegram_response=payload.raw,
                    alert_type=request.alert_type,
                    product_id=request.product_id,
                    recommendation_id=request.recommendation_id,
                    idempotency_key=request.idempotency_key,
                )
                if request.idempotency_key:
                    await self._idempotency_store.record(
                        request.idempotency_key,
                        ttl_seconds=idempotency_ttl_seconds,
                    )
                self.structured_delivery_logging(result)
                await self._emit_event(DashboardEvent.alert_sent, result)
                return result
            except TelegramClientError as exc:
                response_time_ms = int((time.monotonic() - start_time) * 1000)
                if not self._should_retry(exc) or retry_count >= retries:
                    result = self._build_failure_result(
                        request=request,
                        error=exc,
                        response_time_ms=response_time_ms,
                        retry_count=retry_count,
                    )
                    self.structured_delivery_logging(result)
                    await self._emit_event("telegram.delivery_failed", result)
                    return result

                retry_count += 1
                await asyncio.sleep(self._compute_backoff_seconds(retry_count, exc))

    def structured_delivery_logging(self, result: TelegramDeliveryResult) -> None:
        payload = {
            "alert_type": result.alert_type,
            "delivery_status": result.status.value,
            "response_time_ms": result.response_time_ms,
            "retry_count": result.retry_count,
            "telegram_response": result.telegram_response,
            "timestamp": result.timestamp.isoformat(),
            "product_id": result.product_id,
            "recommendation_id": result.recommendation_id,
            "chat_id": result.chat_id,
            "idempotency_key": result.idempotency_key,
        }
        safe_payload = {key: value for key, value in payload.items() if value is not None}
        serialized = json.dumps(safe_payload, ensure_ascii=False, default=str)
        level = logging.INFO if result.success else logging.WARNING
        self._logger.log(level, f"telegram_delivery {serialized}")

    def _resolve_chat_id(self, chat_id: int | str | None) -> int | str:
        resolved_chat_id = chat_id or self._settings.default_chat_id
        if resolved_chat_id is None:
            raise TelegramInvalidChatError("Chat id must be provided for Telegram delivery.")
        return TelegramClient.validate_chat_id(resolved_chat_id)

    async def _send_once(self, request: TelegramSendRequest) -> TelegramMessagePayload:
        if not request.text or not request.text.strip():
            raise TelegramPayloadError("Telegram message content is empty.")
        message = await self._client.send_message(
            chat_id=request.chat_id,
            text=request.text,
            parse_mode=request.parse_mode,
            disable_web_page_preview=request.disable_web_page_preview,
        )
        return TelegramMessagePayload.from_message(message)

    def _should_retry(self, error: TelegramClientError) -> bool:
        if isinstance(error, (TelegramUnauthorizedError, TelegramInvalidChatError, TelegramPayloadError)):
            return False
        return isinstance(
            error,
            (TelegramTimeoutError, TelegramNetworkError, TelegramRateLimitError, TelegramApiError),
        )

    def _compute_backoff_seconds(self, retry_count: int, error: TelegramClientError) -> float:
        base_delay = 1.0
        wait_seconds = base_delay * (2 ** (retry_count - 1))
        if isinstance(error, TelegramRateLimitError) and error.retry_after:
            wait_seconds = max(wait_seconds, float(error.retry_after))
        return wait_seconds

    def _build_idempotency_key(self, request: TelegramSendRequest) -> str:
        payload = {
            "chat_id": str(request.chat_id),
            "text": request.text,
            "alert_type": request.alert_type,
            "product_id": request.product_id,
            "recommendation_id": request.recommendation_id,
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _build_failure_result(
        self,
        *,
        request: TelegramSendRequest,
        error: TelegramClientError,
        response_time_ms: int | None,
        retry_count: int,
    ) -> TelegramDeliveryResult:
        return TelegramDeliveryResult(
            success=False,
            status=DeliveryStatus.failed,
            detail=str(error),
            chat_id=request.chat_id,
            response_time_ms=response_time_ms,
            retry_count=retry_count,
            alert_type=request.alert_type,
            product_id=request.product_id,
            recommendation_id=request.recommendation_id,
            idempotency_key=request.idempotency_key,
        )

    async def _emit_event(self, event: str, result: TelegramDeliveryResult) -> None:
        if not self._event_emitter:
            return
        await self._event_emitter(event, result.model_dump(mode="json"))


def run_async(coro: Awaitable[TelegramDeliveryResult]) -> TelegramDeliveryResult:
    """Run async Telegram delivery from sync contexts (e.g., Celery workers)."""
    return run_async_core(coro)


async def example_usage() -> None:
    """Example: send a formatted Telegram alert."""
    logger = logging.getLogger("app.telegram")
    service = TelegramService(logger=logger)
    alert = AlertMessageContext(
        product_name="Dove Body Lotion 200ml",
        action="PRICE LOWER করুন",
        suggested_price_min=295,
        suggested_price_max=305,
        competitor_insight="2 competitors are currently out-of-stock.",
        opportunity="Lowering price may capture market demand.",
        confidence="HIGH",
        revenue_opportunity=4200,
        product_id="prod_123",
        recommendation_id="rec_456",
    )
    await service.send_alert_message(alert)