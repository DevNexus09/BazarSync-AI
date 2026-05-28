from __future__ import annotations

import json
import logging
import time
from typing import Iterable

import socketio

from app.websocket.socket_events import RealtimeEvent


class SocketEmitter:
    """Emit structured realtime events through the Socket.IO server."""

    def __init__(self, server: socketio.AsyncServer, logger: logging.Logger | None = None) -> None:
        self._server = server
        self._logger = logger or logging.getLogger(__name__)

    async def emit_event(
        self,
        event: RealtimeEvent,
        *,
        rooms: Iterable[str] | None = None,
        to: str | None = None,
        skip_sid: str | None = None,
    ) -> None:
        payload = event.model_dump(mode="json", by_alias=True)
        serialized = json.dumps(payload, default=str)
        target_rooms = list(rooms or [])
        started = time.perf_counter()
        await self._server.emit(
            payload["event"],
            payload,
            to=to or target_rooms or None,
            skip_sid=skip_sid,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        self._logger.info(
            "socket_emit event=%s rooms=%s to=%s size_bytes=%s latency_ms=%s",
            payload["event"],
            target_rooms,
            to,
            len(serialized),
            elapsed_ms,
        )
