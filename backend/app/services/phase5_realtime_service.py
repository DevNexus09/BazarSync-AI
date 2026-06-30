from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

import socketio

from app.core.config import settings
from app.websocket.socket_events import DashboardRealtimeEnvelope, RealtimeEventType
from app.websocket.socket_manager import get_socket_emitter
from app.websocket.socket_rooms import product_room, seller_room

logger = logging.getLogger(__name__)


class Phase5RealtimePublisher:
    def __init__(self, log: logging.Logger | None = None) -> None:
        self._log = log or logger
        self._redis_manager: socketio.AsyncRedisManager | None = None

    async def publish(
        self,
        *,
        event: RealtimeEventType,
        seller_id: UUID,
        product_id: UUID,
        data: dict,
        occurred_at: datetime | None = None,
    ) -> bool:
        envelope = DashboardRealtimeEnvelope(
            event=event,
            seller_id=seller_id,
            product_id=product_id,
            occurred_at=_ensure_utc(occurred_at),
            data=data,
        )
        rooms = [seller_room(str(seller_id)), product_room(str(product_id))]
        try:
            emitter = get_socket_emitter()
            await emitter.emit_event(
                envelope,
                rooms=rooms,
            )
            self._log.info(
                "phase5_realtime_publish_succeeded event=%s seller_id=%s product_id=%s",
                event.value,
                seller_id,
                product_id,
            )
            return True
        except Exception as exc:
            if await self._publish_via_redis(envelope, rooms=rooms):
                return True
            self._log.warning(
                "phase5_realtime_publish_failed event=%s seller_id=%s product_id=%s error=%s",
                event.value,
                seller_id,
                product_id,
                exc,
            )
            return False

    async def _publish_via_redis(
        self,
        envelope: DashboardRealtimeEnvelope,
        *,
        rooms: list[str],
    ) -> bool:
        if not settings.redis_broker_url:
            return False
        try:
            manager = self._get_redis_manager()
            payload = envelope.model_dump(mode="json", by_alias=True)
            await manager.emit(payload["event"], payload, room=rooms)
            self._log.info(
                "phase5_realtime_redis_publish_succeeded event=%s seller_id=%s product_id=%s",
                payload["event"],
                payload["seller_id"],
                payload["product_id"],
            )
            return True
        except Exception as exc:
            self._log.warning(
                "phase5_realtime_redis_publish_failed event=%s seller_id=%s product_id=%s error=%s",
                envelope.event.value,
                envelope.seller_id,
                envelope.product_id,
                exc,
            )
            return False

    def _get_redis_manager(self) -> socketio.AsyncRedisManager:
        if self._redis_manager is None:
            self._redis_manager = socketio.AsyncRedisManager(
                settings.redis_broker_url,
                write_only=True,
                logger=self._log,
            )
        return self._redis_manager


def _ensure_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
