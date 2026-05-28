from __future__ import annotations

from app.services.dashboard.events import DashboardEventEmitter
from app.websocket.socket_manager import socket_manager


async def get_dashboard_event_emitter() -> DashboardEventEmitter:
    return socket_manager
