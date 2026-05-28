from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ConnectionState:
    sid: str
    session_id: str
    rooms: set[str] = field(default_factory=set)
    connected_at: datetime = field(default_factory=_utcnow)
    last_seen: datetime = field(default_factory=_utcnow)
    seller_id: str | None = None


@dataclass
class SessionState:
    session_id: str
    rooms: set[str]
    last_seen: datetime
    expires_at: datetime
    seller_id: str | None = None


class ConnectionManager:
    """Tracks active Socket.IO connections and reconnectable session state."""

    def __init__(
        self,
        *,
        session_ttl_seconds: int,
        heartbeat_timeout_seconds: int,
        logger: logging.Logger | None = None,
    ) -> None:
        self._session_ttl_seconds = session_ttl_seconds
        self._heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._logger = logger or logging.getLogger(__name__)
        self._connections: dict[str, ConnectionState] = {}
        self._sessions: dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def register_connection(
        self,
        sid: str,
        session_id: str,
        *,
        seller_id: str | None = None,
    ) -> set[str]:
        async with self._lock:
            restored_rooms: set[str] = set()
            previous = self._sessions.pop(session_id, None)
            if previous:
                restored_rooms = set(previous.rooms)
            self._connections[sid] = ConnectionState(
                sid=sid,
                session_id=session_id,
                rooms=restored_rooms,
                seller_id=seller_id,
            )
            return restored_rooms

    async def mark_seen(self, sid: str) -> None:
        async with self._lock:
            state = self._connections.get(sid)
            if state:
                state.last_seen = _utcnow()

    async def add_rooms(self, sid: str, rooms: set[str]) -> set[str]:
        async with self._lock:
            state = self._connections.get(sid)
            if not state:
                return set()
            state.rooms.update(rooms)
            return set(state.rooms)

    async def remove_rooms(self, sid: str, rooms: set[str]) -> set[str]:
        async with self._lock:
            state = self._connections.get(sid)
            if not state:
                return set()
            state.rooms.difference_update(rooms)
            return set(state.rooms)

    async def get_rooms(self, sid: str) -> set[str]:
        async with self._lock:
            state = self._connections.get(sid)
            if not state:
                return set()
            return set(state.rooms)

    async def mark_disconnected(self, sid: str) -> SessionState | None:
        async with self._lock:
            state = self._connections.pop(sid, None)
            if not state:
                return None
            expires_at = _utcnow() + timedelta(seconds=self._session_ttl_seconds)
            session = SessionState(
                session_id=state.session_id,
                rooms=set(state.rooms),
                last_seen=state.last_seen,
                expires_at=expires_at,
                seller_id=state.seller_id,
            )
            self._sessions[state.session_id] = session
            return session

    async def stale_connection_ids(self) -> list[str]:
        now = _utcnow()
        timeout = timedelta(seconds=self._heartbeat_timeout_seconds)
        async with self._lock:
            return [
                sid
                for sid, state in self._connections.items()
                if now - state.last_seen > timeout
            ]

    async def cleanup_sessions(self) -> int:
        now = _utcnow()
        async with self._lock:
            stale = [sid for sid, session in self._sessions.items() if session.expires_at < now]
            for session_id in stale:
                self._sessions.pop(session_id, None)
            return len(stale)

    async def snapshot(self) -> dict[str, int]:
        async with self._lock:
            return {
                "connections": len(self._connections),
                "sessions": len(self._sessions),
            }
