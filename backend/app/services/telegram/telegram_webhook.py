from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.telegram.telegram_connection_service import (
    ConnectionNotFoundError,
    ConnectionTokenExpiredError,
    ConnectionTokenInvalidError,
    TelegramConnectionService,
    TelegramUserSnapshot,
)
from app.services.telegram.telegram_service import TelegramService


class TelegramChat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    type: str


class TelegramUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    is_bot: bool | None = None
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None


class TelegramMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message_id: int
    date: int
    chat: TelegramChat
    from_user: TelegramUser = Field(alias="from")
    text: str | None = None


class TelegramUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    update_id: int
    message: TelegramMessage | None = None


class TelegramWebhookHandler:
    def __init__(
        self,
        connection_service: TelegramConnectionService,
        telegram_service: TelegramService,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._connections = connection_service
        self._telegram = telegram_service
        self._logger = logger or logging.getLogger(__name__)

    async def handle(self, payload: dict[str, Any]) -> None:
        try:
            update = TelegramUpdate.model_validate(payload)
        except ValidationError as exc:
            self._logger.warning("telegram_webhook_invalid_payload error=%s", exc)
            return

        message = update.message
        if not message or not message.text:
            return

        chat_id = message.chat.id
        command, argument = self._parse_command(message.text)
        user_snapshot = TelegramUserSnapshot(
            telegram_chat_id=str(chat_id),
            telegram_username=message.from_user.username,
            telegram_first_name=message.from_user.first_name,
            telegram_last_name=message.from_user.last_name,
        )

        if command == "/start":
            await self._send_message(chat_id, self._start_message())
            return
        if command == "/help":
            await self._send_message(chat_id, self._help_message())
            return
        if command == "/connect":
            await self._handle_connect(chat_id, argument, user_snapshot)
            return
        if command == "/disconnect":
            await self._handle_disconnect(chat_id)
            return
        if command == "/status":
            await self._handle_status(chat_id)
            return

        await self._send_message(chat_id, self._unknown_command_message())

    async def _handle_connect(
        self,
        chat_id: int,
        token: str | None,
        user: TelegramUserSnapshot,
    ) -> None:
        if not token:
            await self._send_message(chat_id, "Please provide your connect token.")
            return
        try:
            connection = await self._connections.connect_with_token(
                token,
                chat_id=chat_id,
                user=user,
            )
        except ConnectionTokenExpiredError:
            await self._send_message(
                chat_id,
                "⚠️ That token has expired. Please generate a new token from the dashboard.",
            )
            return
        except ConnectionTokenInvalidError:
            await self._send_message(
                chat_id,
                "❌ Token not recognized. Please copy the latest token from the dashboard.",
            )
            return

        await self._send_message(
            chat_id,
            "✅ Your Telegram account is now connected to SMEBoost War Room Alerts.",
        )
        self._logger.info(
            "telegram_connect_success seller_id=%s chat_id=%s",
            connection.seller_id,
            connection.telegram_chat_id,
        )

    async def _handle_disconnect(self, chat_id: int) -> None:
        try:
            await self._connections.disconnect_by_chat_id(chat_id)
        except ConnectionNotFoundError:
            await self._send_message(chat_id, "You are not connected yet.")
            return
        await self._send_message(chat_id, "✅ Telegram alerts have been disconnected.")

    async def _handle_status(self, chat_id: int) -> None:
        connection = await self._connections.get_by_chat_id(chat_id)
        if not connection or not connection.is_connected:
            await self._send_message(chat_id, "You are not connected to any seller yet.")
            return
        username = connection.telegram_username or connection.telegram_first_name or "seller"
        await self._send_message(
            chat_id,
            f"✅ Connected to {username}. Alerts will arrive here.",
        )

    async def _send_message(self, chat_id: int, text: str) -> None:
        await self._telegram.send_text_message(text, chat_id=chat_id)

    @staticmethod
    def _parse_command(text: str) -> tuple[str, str | None]:
        cleaned = text.strip()
        if not cleaned.startswith("/"):
            return "", None
        parts = cleaned.split()
        command = parts[0].split("@")[0].lower()
        argument = parts[1] if len(parts) > 1 else None
        return command, argument

    @staticmethod
    def _start_message() -> str:
        return (
            "👋 Welcome to SMEBoost War Room Alerts.\n\n"
            "To connect your account:\n"
            "1. Open your dashboard\n"
            "2. Click Connect Telegram\n"
            "3. Send /connect <token> here\n\n"
            "Need help? Use /help."
        )

    @staticmethod
    def _help_message() -> str:
        return (
            "Commands:\n"
            "/connect <token> — link your seller account\n"
            "/disconnect — unlink alerts\n"
            "/status — view connection status\n"
            "/help — show this message"
        )

    @staticmethod
    def _unknown_command_message() -> str:
        return "Command not recognized. Use /help to see available commands."
