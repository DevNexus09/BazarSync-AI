from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as core_settings
from app.models.telegram_connection import SellerTelegramConnection
from app.websocket.socket_emitter import SocketEmitter
from app.websocket.socket_events import (
    TelegramConnectionPayload,
    TelegramConnectionSnapshot,
    TelegramConnectedEvent,
    TelegramDisconnectedEvent,
)
from app.websocket.socket_rooms import seller_room
from app.websocket.socket_manager import get_socket_emitter

_CURRENT_DIR = Path(__file__).resolve()
_BACKEND_ENV = _CURRENT_DIR.parents[3] / ".env"
_ROOT_ENV = _CURRENT_DIR.parents[4] / ".env"


class TelegramConnectionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TELEGRAM_",
        env_file=(str(_BACKEND_ENV), str(_ROOT_ENV), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    connect_token_ttl_minutes: int = Field(default=10, ge=1)
    connect_token_secret: str | None = None
    webhook_secret: str | None = None
    webhook_url: str | None = None
    alert_cooldown_seconds: int = Field(default=7200, ge=0)
    bot_username: str | None = None

    @property
    def resolved_token_secret(self) -> str:
        return self.connect_token_secret or core_settings.jwt_secret_key


class TelegramConnectionError(Exception):
    """Base error for Telegram connection operations."""


class ConnectionTokenInvalidError(TelegramConnectionError):
    """Raised when a connection token is invalid."""


class ConnectionTokenExpiredError(TelegramConnectionError):
    """Raised when a connection token has expired."""


class ConnectionNotFoundError(TelegramConnectionError):
    """Raised when a seller connection is missing."""


class TelegramUserSnapshot(BaseModel):
    telegram_chat_id: str
    telegram_username: str | None
    telegram_first_name: str | None
    telegram_last_name: str | None


@dataclass(frozen=True)
class ConnectionToken:
    token: str
    expires_at: datetime


class TelegramConnectionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: TelegramConnectionSettings | None = None,
        logger: logging.Logger | None = None,
        emitter: SocketEmitter | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or TelegramConnectionSettings()
        self._logger = logger or logging.getLogger(__name__)
        self._emitter = emitter

    @property
    def settings(self) -> TelegramConnectionSettings:
        return self._settings

    async def generate_connect_token(self, seller_id: str) -> ConnectionToken:
        token = secrets.token_urlsafe(32)
        hashed = self._hash_token(token)
        expires_at = self._now() + timedelta(minutes=self._settings.connect_token_ttl_minutes)
        connection = await self._get_or_create_connection(seller_id)
        connection.connection_token = hashed
        connection.token_expires_at = expires_at
        await self._session.commit()
        await self._session.refresh(connection)
        self._logger.info(
            "telegram_connect_token_issued seller_id=%s expires_at=%s",
            seller_id,
            expires_at.isoformat(),
        )
        return ConnectionToken(token=token, expires_at=expires_at)

    async def get_status(self, seller_id: str) -> SellerTelegramConnection | None:
        statement = select(SellerTelegramConnection).where(
            SellerTelegramConnection.seller_id == seller_id
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def connect_with_token(
        self,
        token: str,
        *,
        chat_id: int | str,
        user: TelegramUserSnapshot,
    ) -> SellerTelegramConnection:
        hashed = self._hash_token(token)
        statement = select(SellerTelegramConnection).where(
            SellerTelegramConnection.connection_token == hashed
        )
        connection = (await self._session.execute(statement)).scalar_one_or_none()
        if not connection:
            self._logger.warning("telegram_connect_invalid token_hash=%s", hashed)
            raise ConnectionTokenInvalidError("Connection token is invalid.")

        if connection.token_expires_at and connection.token_expires_at <= self._now():
            connection.connection_token = None
            connection.token_expires_at = None
            await self._session.commit()
            self._logger.info("telegram_connect_expired seller_id=%s", connection.seller_id)
            raise ConnectionTokenExpiredError("Connection token has expired.")

        connection.telegram_chat_id = str(chat_id)
        connection.telegram_username = user.telegram_username
        connection.telegram_first_name = user.telegram_first_name
        connection.telegram_last_name = user.telegram_last_name
        connection.is_connected = True
        connection.connected_at = self._now()
        connection.connection_token = None
        connection.token_expires_at = None
        await self._session.commit()
        await self._session.refresh(connection)
        await self._emit_connection_event(connection, connected=True)
        self._logger.info(
            "telegram_connected seller_id=%s chat_id=%s username=%s",
            connection.seller_id,
            connection.telegram_chat_id,
            connection.telegram_username,
        )
        return connection

    async def disconnect_seller(self, seller_id: str) -> SellerTelegramConnection:
        statement = select(SellerTelegramConnection).where(
            SellerTelegramConnection.seller_id == seller_id
        )
        connection = (await self._session.execute(statement)).scalar_one_or_none()
        if not connection:
            raise ConnectionNotFoundError("Seller telegram connection not found.")
        await self._clear_connection(connection)
        return connection

    async def disconnect_by_chat_id(self, chat_id: int | str) -> SellerTelegramConnection:
        statement = select(SellerTelegramConnection).where(
            SellerTelegramConnection.telegram_chat_id == str(chat_id)
        )
        connection = (await self._session.execute(statement)).scalar_one_or_none()
        if not connection:
            raise ConnectionNotFoundError("Telegram chat is not linked.")
        await self._clear_connection(connection)
        return connection

    async def get_by_chat_id(self, chat_id: int | str) -> SellerTelegramConnection | None:
        statement = select(SellerTelegramConnection).where(
            SellerTelegramConnection.telegram_chat_id == str(chat_id)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def mark_alert_sent(self, seller_id: str, sent_at: datetime | None = None) -> None:
        statement = select(SellerTelegramConnection).where(
            SellerTelegramConnection.seller_id == seller_id
        )
        connection = (await self._session.execute(statement)).scalar_one_or_none()
        if not connection:
            return
        connection.last_alert_sent_at = sent_at or self._now()
        await self._session.commit()

    async def _get_or_create_connection(self, seller_id: str) -> SellerTelegramConnection:
        existing = await self.get_status(seller_id)
        if existing:
            return existing
        connection = SellerTelegramConnection(seller_id=seller_id, is_connected=False)
        self._session.add(connection)
        await self._session.commit()
        await self._session.refresh(connection)
        return connection

    async def _clear_connection(self, connection: SellerTelegramConnection) -> None:
        connection.telegram_chat_id = None
        connection.telegram_username = None
        connection.telegram_first_name = None
        connection.telegram_last_name = None
        connection.is_connected = False
        connection.connected_at = None
        connection.connection_token = None
        connection.token_expires_at = None
        await self._session.commit()
        await self._session.refresh(connection)
        await self._emit_connection_event(connection, connected=False)
        self._logger.info("telegram_disconnected seller_id=%s", connection.seller_id)

    def _hash_token(self, token: str) -> str:
        secret = self._settings.resolved_token_secret.encode("utf-8")
        return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def _emit_connection_event(
        self,
        connection: SellerTelegramConnection,
        *,
        connected: bool,
    ) -> None:
        emitter = self._resolve_emitter()
        if not emitter:
            return
        snapshot = TelegramConnectionSnapshot(
            id=connection.id,
            is_connected=connection.is_connected,
            telegram_username=connection.telegram_username,
            telegram_first_name=connection.telegram_first_name,
            telegram_last_name=connection.telegram_last_name,
            connected_at=connection.connected_at,
            last_alert_sent_at=connection.last_alert_sent_at,
        )
        payload = TelegramConnectionPayload(connection=snapshot)
        event = (
            TelegramConnectedEvent(payload=payload, seller_id=connection.seller_id)
            if connected
            else TelegramDisconnectedEvent(payload=payload, seller_id=connection.seller_id)
        )
        await emitter.emit_event(event, rooms=[seller_room(str(connection.seller_id))])

    def _resolve_emitter(self) -> SocketEmitter | None:
        if self._emitter is not None:
            return self._emitter
        try:
            self._emitter = get_socket_emitter()
        except RuntimeError:
            self._logger.debug("socket_emitter_unavailable")
            return None
        return self._emitter
