from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import socketio

from app.core.config import settings


@dataclass(frozen=True)
class SocketIOResources:
    server: socketio.AsyncServer
    app: Callable


class SafeSocketIOApp:
    def __init__(
        self,
        app: socketio.ASGIApp,
        *,
        socketio_path: str,
        mount_path: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._app = app
        self._logger = logger or logging.getLogger(__name__)
        cleaned_socket_path = socketio_path.strip("/") if socketio_path else ""
        socket_prefix = f"/{cleaned_socket_path}" if cleaned_socket_path else "/"
        prefixes = {socket_prefix}
        if mount_path:
            cleaned_mount = "/" + mount_path.strip("/")
            if cleaned_mount != "/":
                prefixes.add(f"{cleaned_mount}{socket_prefix}")
        self._socketio_prefixes = tuple(sorted(prefixes, key=len, reverse=True))

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            path = scope.get("path", "")
            if not any(path.startswith(prefix) for prefix in self._socketio_prefixes):
                self._logger.warning(
                    "socket_path_mismatch expected_prefixes=%s path=%s",
                    ",".join(self._socketio_prefixes),
                    path,
                )
                await send({"type": "websocket.accept"})
                await send({"type": "websocket.close"})
                return
        await self._app(scope, receive, send)


def _build_client_manager() -> socketio.AsyncRedisManager | None:
    if not settings.redis_broker_url:
        return None
    return socketio.AsyncRedisManager(settings.redis_broker_url)


def _normalize_socketio_path(path: str) -> str:
    cleaned = path.strip()
    if not cleaned:
        return "socket.io"
    return cleaned.lstrip("/")


def build_socketio_resources(
    logger: logging.Logger | None = None,
) -> SocketIOResources:
    client_manager = _build_client_manager()
    socketio_path = _normalize_socketio_path(settings.socketio_path)
    server = socketio.AsyncServer(
        async_mode="asgi",
        cors_allowed_origins=settings.cors_origins,
        ping_interval=settings.socketio_ping_interval,
        ping_timeout=settings.socketio_ping_timeout,
        max_http_buffer_size=settings.socketio_max_http_buffer_size,
        client_manager=client_manager,
        logger=logger,
        engineio_logger=logger,
    )
    raw_app = socketio.ASGIApp(server, socketio_path=socketio_path)
    app = SafeSocketIOApp(
        raw_app,
        socketio_path=socketio_path,
        mount_path=settings.socketio_mount_path,
        logger=logger,
    )
    return SocketIOResources(server=server, app=app)
