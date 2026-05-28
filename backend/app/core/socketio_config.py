from __future__ import annotations

import logging
from dataclasses import dataclass

import socketio

from app.core.config import settings


@dataclass(frozen=True)
class SocketIOResources:
    server: socketio.AsyncServer
    app: socketio.ASGIApp


def _build_client_manager() -> socketio.AsyncRedisManager | None:
    if not settings.redis_broker_url:
        return None
    return socketio.AsyncRedisManager(settings.redis_broker_url)


def build_socketio_resources(
    logger: logging.Logger | None = None,
) -> SocketIOResources:
    client_manager = _build_client_manager()
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
    app = socketio.ASGIApp(server, socketio_path=settings.socketio_path)
    return SocketIOResources(server=server, app=app)
