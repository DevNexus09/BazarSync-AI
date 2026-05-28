from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.telegram_connection import SellerTelegramConnection
from app.models.telegram_snapshot_log import TelegramProductSnapshotLog
from app.schemas.product_snapshot import ProductSnapshot
from app.services.recommendation_service import (
    CompetitorDataNotFoundError as AnalyticsCompetitorDataNotFoundError,
    ProductNotFoundError as AnalyticsProductNotFoundError,
    RecommendationNotFoundError,
    RecommendationService,
)
from app.services.telegram.snapshot_formatter import format_product_snapshot
from app.services.telegram.telegram_client import TelegramClientError
from app.services.telegram.telegram_service import DeliveryStatus, TelegramDeliveryResult, TelegramService
from app.websocket.socket_events import ProductSnapshotSentEvent, ProductSnapshotSentPayload
from app.websocket.socket_manager import get_socket_emitter
from app.websocket.socket_rooms import seller_room


class ProductSnapshotServiceError(Exception):
    status_code = 500
    error_code = "snapshot_error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class TelegramNotConnectedError(ProductSnapshotServiceError):
    status_code = 400
    error_code = "telegram_not_connected"


class ProductNotFoundError(ProductSnapshotServiceError):
    status_code = 404
    error_code = "product_not_found"


class CompetitorDataNotFoundError(ProductSnapshotServiceError):
    status_code = 404
    error_code = "competitor_data_missing"


class SnapshotRecommendationNotFoundError(ProductSnapshotServiceError):
    status_code = 404
    error_code = "recommendation_not_found"


class TelegramDeliveryFailedError(ProductSnapshotServiceError):
    status_code = 502
    error_code = "telegram_delivery_failed"

    def __init__(self, detail: str, *, error_code: str | None = None) -> None:
        super().__init__(detail)
        if error_code:
            self.error_code = error_code


@dataclass(frozen=True)
class ProductSnapshotDeliveryResult:
    sent_at: datetime
    delivery_status: str


class ProductSnapshotService:
    def __init__(
        self,
        db: Session,
        *,
        telegram_service: TelegramService | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._db = db
        self._logger = logger or logging.getLogger(__name__)
        self._telegram = telegram_service or TelegramService(logger=self._logger)
        self._recommendations = RecommendationService(db, logger=self._logger)

    async def send_snapshot(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
    ) -> ProductSnapshotDeliveryResult:
        connection = self._get_connection(seller_id)
        if not connection or not connection.is_connected or not connection.telegram_chat_id:
            raise TelegramNotConnectedError(
                "Connect your Telegram account first to send product snapshots."
            )

        try:
            product = self._recommendations.load_product(seller_id, product_id)
        except AnalyticsProductNotFoundError as exc:
            raise ProductNotFoundError("Product not found.") from exc

        try:
            competitors = self._recommendations.load_competitors(seller_id, product_id)
            analytics = self._recommendations.run_analytics(product, competitors)
        except AnalyticsCompetitorDataNotFoundError as exc:
            raise CompetitorDataNotFoundError(
                "No competitor data found for this product yet."
            ) from exc

        try:
            latest = self._recommendations.get_latest_recommendation(
                seller_id=seller_id, product_id=product_id
            )
        except RecommendationNotFoundError as exc:
            raise SnapshotRecommendationNotFoundError(
                "No AI recommendation found for this product yet."
            ) from exc

        snapshot = ProductSnapshot(
            seller_id=seller_id,
            product_id=product_id,
            product_name=product.title,
            current_price=float(product.selling_price),
            current_stock=product.stock_quantity,
            supplier_lead_time=product.supplier_lead_time,
            competitor_median_price=_to_float(analytics.get("competitor_median_price")),
            price_gap_percent=_to_float(analytics.get("price_gap_percent")),
            recommendation_action=latest.recommendation.action,
            ai_reason=latest.recommendation.reasoning_bn,
            confidence=latest.recommendation.confidence,
            updated_at=latest.created_at,
        )
        message = format_product_snapshot(snapshot)

        try:
            result = await self._telegram.send_text_message(
                message, chat_id=connection.telegram_chat_id
            )
        except TelegramClientError as exc:
            await self._record_log(
                seller_id=seller_id,
                product_id=product_id,
                chat_id=connection.telegram_chat_id,
                status=DeliveryStatus.failed.value,
                sent_at=self._now(),
                error_message=str(exc),
            )
            detail, error_code = _map_delivery_error(str(exc))
            raise TelegramDeliveryFailedError(detail, error_code=error_code) from exc
        else:
            await self._record_delivery(connection, product_id, result)

        if result.status is not DeliveryStatus.delivered:
            detail, error_code = _map_delivery_error(result.detail or "")
            raise TelegramDeliveryFailedError(detail, error_code=error_code)

        await self._emit_snapshot_sent(
            seller_id=seller_id,
            product_id=product_id,
            product_title=product.title,
            sent_at=result.timestamp,
        )

        return ProductSnapshotDeliveryResult(
            sent_at=result.timestamp,
            delivery_status=result.status.value,
        )

    def _get_connection(self, seller_id: UUID) -> SellerTelegramConnection | None:
        statement = select(SellerTelegramConnection).where(
            SellerTelegramConnection.seller_id == seller_id
        )
        return self._db.execute(statement).scalar_one_or_none()

    async def _record_delivery(
        self,
        connection: SellerTelegramConnection,
        product_id: UUID,
        result: TelegramDeliveryResult,
    ) -> None:
        if result.status is DeliveryStatus.delivered:
            connection.last_alert_sent_at = result.timestamp

        await self._record_log(
            seller_id=connection.seller_id,
            product_id=product_id,
            chat_id=str(result.chat_id or connection.telegram_chat_id),
            status=result.status.value,
            sent_at=result.timestamp,
            error_message=result.detail if result.status is not DeliveryStatus.delivered else None,
        )

    async def _record_log(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        chat_id: str,
        status: str,
        sent_at: datetime,
        error_message: str | None,
    ) -> None:
        log = TelegramProductSnapshotLog(
            seller_id=seller_id,
            product_id=product_id,
            telegram_chat_id=chat_id,
            status=status,
            sent_at=sent_at,
            error_message=error_message,
        )
        self._db.add(log)
        self._db.commit()

    async def _emit_snapshot_sent(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        product_title: str,
        sent_at: datetime,
    ) -> None:
        try:
            emitter = get_socket_emitter()
        except RuntimeError:
            self._logger.debug("socket_emitter_unavailable")
            return
        event = ProductSnapshotSentEvent(
            payload=ProductSnapshotSentPayload(
                seller_id=seller_id,
                product_id=product_id,
                timestamp=sent_at,
                product_title=product_title,
            ),
            seller_id=seller_id,
            product_id=product_id,
        )
        await emitter.emit_event(event, rooms=[seller_room(str(seller_id))])

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _map_delivery_error(detail: str) -> tuple[str, str]:
    lowered = detail.lower()
    if any(
        phrase in lowered
        for phrase in (
            "chat not found",
            "chat id is invalid",
            "chat id format is invalid",
            "does not have access to the chat",
            "user not found",
            "invalid user id",
        )
    ):
        return (
            "Your Telegram connection expired. Please reconnect @bazarsync_bot.",
            "telegram_connection_expired",
        )
    if "bot token" in lowered or "unauthorized" in lowered:
        return (
            "Telegram bot authorization failed. Please contact support.",
            "telegram_unauthorized",
        )
    if "rate limit" in lowered:
        return (
            "Telegram rate limit exceeded. Please try again shortly.",
            "telegram_rate_limited",
        )
    if "timeout" in lowered:
        return (
            "Telegram delivery timed out. Please try again.",
            "telegram_timeout",
        )
    if "network" in lowered:
        return (
            "Telegram network error. Please try again.",
            "telegram_network_error",
        )
    if detail:
        return (detail, "telegram_delivery_failed")
    return ("Telegram delivery failed. Please try again.", "telegram_delivery_failed")
