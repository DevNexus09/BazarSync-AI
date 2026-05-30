"""Socket.IO lifecycle and event wiring for realtime dashboard events."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Literal
from uuid import UUID, uuid4

import socketio
from fastapi import FastAPI
from jwt import ExpiredSignatureError, InvalidTokenError
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import settings
from app.core.security import decode_access_token
from app.core.socketio_config import build_socketio_resources
from app.db.async_session import AsyncSessionLocal
from app.models.product import Product
from app.models.seller import Seller
from app.websocket.connection_manager import ConnectionManager
from app.websocket.socket_emitter import SocketEmitter
from app.websocket.socket_events import (
    ConnectionEstablishedEvent,
    ConnectionEstablishedPayload,
    RealtimeErrorEvent,
    RealtimeErrorPayload,
    RoomsUpdatedEvent,
    RoomsUpdatedPayload,
    ServerPongEvent,
    ServerPongPayload,
)
from app.websocket.socket_rooms import (
    ACTIVITY_ROOM,
    ALERTS_ROOM,
    DASHBOARD_ROOM,
    RoomScope,
    RoomSubscriptionRequest,
    resolve_room,
    seller_room,
    product_room,
)


class RealtimeSocketManager:
    def __init__(
        self,
        server: socketio.AsyncServer,
        connection_manager: ConnectionManager,
        emitter: SocketEmitter,
        logger: logging.Logger | None = None,
    ) -> None:
        self._server = server
        self._connections = connection_manager
        self._emitter = emitter
        self._logger = logger or logging.getLogger(__name__)
        self._heartbeat_task: asyncio.Task | None = None

    def register_handlers(self) -> None:
        @self._server.event
        async def connect(sid: str, _environ: dict, auth: dict | None) -> bool:
            auth = auth or {}
            auth_result = await self._authenticate(auth)
            if not auth_result:
                return False
            seller_id, session_id = auth_result
            restored_rooms = await self._connections.register_connection(
                sid, session_id, seller_id=seller_id
            )
            for room in restored_rooms:
                await self._server.enter_room(sid, room)
            await self._connections.mark_seen(sid)
            await self._emit_connection_established(sid, session_id, restored_rooms)
            if restored_rooms:
                await self._emit_rooms_updated(sid, restored_rooms, action="restored")
            self._logger.info(
                "socket_connected sid=%s session_id=%s restored_rooms=%s",
                sid,
                session_id,
                list(restored_rooms),
            )
            return True

        @self._server.event
        async def disconnect(sid: str) -> None:
            session = await self._connections.mark_disconnected(sid)
            self._logger.info(
                "socket_disconnected sid=%s session_id=%s rooms=%s",
                sid,
                session.session_id if session else None,
                list(session.rooms) if session else [],
            )

        @self._server.on("subscribe_rooms")
        async def subscribe_rooms(sid: str, payload: dict | None) -> None:
            await self._connections.mark_seen(sid)
            seller_id = await self._connections.get_seller_id(sid)
            if not seller_id:
                await self._emit_error(
                    sid,
                    code="unauthorized",
                    message="Authentication required to subscribe to rooms.",
                )
                return
            try:
                request = RoomSubscriptionRequest.model_validate(payload or {})
            except ValidationError as exc:
                await self._emit_error(
                    sid,
                    code="invalid_payload",
                    message="Invalid room subscription payload.",
                    details={"error": str(exc)},
                )
                return
            rooms, rejected = await self._resolve_authorized_rooms(
                request, seller_id=seller_id, include_seller_room=True
            )
            if rejected:
                await self._emit_error(
                    sid,
                    code="unauthorized_room",
                    message="One or more requested rooms are not authorized.",
                    details={"rooms": ",".join(rejected)},
                )
            for room in rooms:
                await self._server.enter_room(sid, room)
            active_rooms = await self._connections.add_rooms(sid, rooms)
            await self._emit_rooms_updated(sid, active_rooms, action="joined")
            self._logger.info("socket_rooms_joined sid=%s rooms=%s", sid, list(rooms))

        @self._server.on("unsubscribe_rooms")
        async def unsubscribe_rooms(sid: str, payload: dict | None) -> None:
            await self._connections.mark_seen(sid)
            seller_id = await self._connections.get_seller_id(sid)
            if not seller_id:
                await self._emit_error(
                    sid,
                    code="unauthorized",
                    message="Authentication required to unsubscribe from rooms.",
                )
                return
            try:
                request = RoomSubscriptionRequest.model_validate(payload or {})
            except ValidationError as exc:
                await self._emit_error(
                    sid,
                    code="invalid_payload",
                    message="Invalid room unsubscribe payload.",
                    details={"error": str(exc)},
                )
                return
            rooms, rejected = await self._resolve_authorized_rooms(
                request, seller_id=seller_id, include_seller_room=False
            )
            if rejected:
                await self._emit_error(
                    sid,
                    code="unauthorized_room",
                    message="One or more requested rooms are not authorized.",
                    details={"rooms": ",".join(rejected)},
                )
            for room in rooms:
                await self._server.leave_room(sid, room)
            active_rooms = await self._connections.remove_rooms(sid, rooms)
            await self._emit_rooms_updated(sid, active_rooms, action="left")
            self._logger.info("socket_rooms_left sid=%s rooms=%s", sid, list(rooms))

        @self._server.on("subscribe_war_room")
        async def subscribe_war_room(sid: str, payload: dict | None) -> None:
            await self._connections.mark_seen(sid)
            seller_id = await self._connections.get_seller_id(sid)
            rooms = {DASHBOARD_ROOM, ALERTS_ROOM, ACTIVITY_ROOM}
            if seller_id:
                rooms.add(seller_room(seller_id))
            for room in rooms:
                await self._server.enter_room(sid, room)
            active_rooms = await self._connections.add_rooms(sid, rooms)
            await self._emit_rooms_updated(sid, active_rooms, action="joined")
            self._logger.info(
                "socket_war_room_joined sid=%s seller_id=%s rooms=%s",
                sid,
                seller_id,
                list(rooms),
            )

        @self._server.on("client_ping")
        async def client_ping(sid: str, payload: dict | None) -> None:
            await self._connections.mark_seen(sid)
            client_ts = 0
            if payload and isinstance(payload.get("timestamp"), int):
                client_ts = payload["timestamp"]
            server_ts = int(time.time() * 1000)
            latency_ms = server_ts - client_ts if client_ts else None
            event = ServerPongEvent(
                payload=ServerPongPayload(
                    client_timestamp=client_ts,
                    server_timestamp=server_ts,
                    latency_ms=latency_ms,
                )
            )
            await self._emitter.emit_event(event, to=sid)

    async def _authenticate(self, auth: dict[str, Any]) -> tuple[str, str] | None:
        token = auth.get("token")
        if not token:
            self._logger.warning("socket_auth_missing")
            return None
        try:
            payload = decode_access_token(token)
        except ExpiredSignatureError:
            self._logger.warning("socket_auth_expired")
            return None
        except InvalidTokenError:
            self._logger.warning("socket_auth_invalid")
            return None
        subject = payload.get("sub")
        if not subject:
            self._logger.warning("socket_auth_subject_missing")
            return None
        try:
            seller_uuid = UUID(subject)
        except ValueError:
            self._logger.warning("socket_auth_subject_invalid")
            return None
        async with AsyncSessionLocal() as session:
            seller = await session.get(Seller, seller_uuid)
            if not seller:
                self._logger.warning("socket_auth_seller_not_found seller_id=%s", seller_uuid)
                return None
        session_id = auth.get("session_id") or str(uuid4())
        return str(seller_uuid), session_id

    async def _resolve_authorized_rooms(
        self,
        request: RoomSubscriptionRequest,
        *,
        seller_id: str,
        include_seller_room: bool,
    ) -> tuple[set[str], list[str]]:
        rooms: set[str] = set()
        rejected: list[str] = []
        if include_seller_room:
            rooms.add(seller_room(seller_id))
        for target in request.rooms:
            if target.scope is RoomScope.SELLER:
                if target.id and target.id != seller_id:
                    rejected.append(resolve_room(target) or "seller")
                    continue
                rooms.add(seller_room(seller_id))
                continue
            if target.scope is RoomScope.PRODUCT:
                if not target.id:
                    continue
                if await self._owns_product(seller_id, target.id):
                    rooms.add(product_room(target.id))
                else:
                    rejected.append(resolve_room(target) or f"product:{target.id}")
                continue
            if target.scope in {RoomScope.DASHBOARD, RoomScope.ALERTS, RoomScope.ACTIVITY}:
                resolved = resolve_room(target)
                if resolved:
                    rooms.add(resolved)
                continue
            if target.scope is RoomScope.CUSTOM:
                rejected.append(resolve_room(target) or "custom")
        return rooms, rejected

    async def _owns_product(self, seller_id: str, product_id: str) -> bool:
        try:
            product_uuid = UUID(product_id)
        except ValueError:
            return False
        async with AsyncSessionLocal() as session:
            stmt = select(Product.id).where(
                Product.id == product_uuid,
                Product.seller_id == seller_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def start(self) -> None:
        if self._heartbeat_task:
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._logger.info("socket_heartbeat_started interval=%s", settings.socketio_heartbeat_interval)

    async def shutdown(self) -> None:
        if not self._heartbeat_task:
            return
        self._heartbeat_task.cancel()
        try:
            await self._heartbeat_task
        except asyncio.CancelledError:
            pass
        self._heartbeat_task = None
        self._logger.info("socket_heartbeat_stopped")

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(settings.socketio_heartbeat_interval)
            stale = await self._connections.stale_connection_ids()
            for sid in stale:
                await self._server.disconnect(sid)
                self._logger.warning("socket_stale_disconnect sid=%s", sid)
            cleaned = await self._connections.cleanup_sessions()
            if cleaned:
                self._logger.info("socket_session_cleanup cleaned=%s", cleaned)

    async def _emit_connection_established(
        self, sid: str, session_id: str, rooms: set[str]
    ) -> None:
        event = ConnectionEstablishedEvent(
            payload=ConnectionEstablishedPayload(
                session_id=session_id,
                sid=sid,
                rooms=sorted(rooms),
                heartbeat_interval=settings.socketio_heartbeat_interval,
                heartbeat_timeout=settings.socketio_heartbeat_timeout,
            )
        )
        await self._emitter.emit_event(event, to=sid)

    async def _emit_rooms_updated(
        self,
        sid: str,
        rooms: set[str],
        *,
        action: Literal["joined", "left", "restored"],
    ) -> None:
        event = RoomsUpdatedEvent(
            payload=RoomsUpdatedPayload(rooms=sorted(rooms), action=action)
        )
        await self._emitter.emit_event(event, to=sid)

    async def _emit_error(
        self, sid: str, *, code: str, message: str, details: dict[str, str] | None = None
    ) -> None:
        event = RealtimeErrorEvent(
            payload=RealtimeErrorPayload(code=code, message=message, details=details)
        )
        await self._emitter.emit_event(event, to=sid)


_socket_manager: RealtimeSocketManager | None = None
_socket_emitter: SocketEmitter | None = None


def init_socketio(app: FastAPI) -> RealtimeSocketManager:
    global _socket_manager, _socket_emitter
    if _socket_manager:
        return _socket_manager
    resources = build_socketio_resources(logging.getLogger("app.websocket"))
    connection_manager = ConnectionManager(
        session_ttl_seconds=settings.socketio_session_ttl_seconds,
        heartbeat_timeout_seconds=settings.socketio_heartbeat_timeout,
        logger=logging.getLogger("app.websocket.connection"),
    )
    emitter = SocketEmitter(resources.server, logging.getLogger("app.websocket.emit"))
    manager = RealtimeSocketManager(
        resources.server,
        connection_manager,
        emitter,
        logger=logging.getLogger("app.websocket"),
    )
    manager.register_handlers()
    app.mount(settings.socketio_mount_path, resources.app)
    _socket_manager = manager
    _socket_emitter = emitter
    return manager


def get_socket_emitter() -> SocketEmitter:
    if not _socket_emitter:
        raise RuntimeError("Socket emitter not initialized. Call init_socketio() first.")
    return _socket_emitter


class LegacySocketEmitter:
    """Backward-compatible emitter for legacy DashboardEvent pipelines."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("app.websocket.legacy")

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        if not _socket_manager:
            self._logger.debug("socket_emit_skipped event=%s reason=not_initialized", event)
            return
        await _socket_manager._server.emit(event, payload)


socket_manager = LegacySocketEmitter()
