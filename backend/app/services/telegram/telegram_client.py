from __future__ import annotations

import asyncio
from pathlib import Path
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from telegram import Bot, Message, User
from telegram.error import (
    BadRequest,
    Forbidden,
    InvalidToken,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut,
)
from telegram.request import HTTPXRequest


class TelegramClientError(Exception):
    """Base exception for Telegram client failures."""


class TelegramConfigError(TelegramClientError):
    """Raised when configuration is missing or invalid."""


class TelegramPayloadError(TelegramClientError):
    """Raised when the request payload is malformed."""


class TelegramInvalidChatError(TelegramClientError):
    """Raised when the chat id is invalid or inaccessible."""


class TelegramUnauthorizedError(TelegramClientError):
    """Raised when the bot token is invalid or unauthorized."""


class TelegramTimeoutError(TelegramClientError):
    """Raised when the Telegram API times out."""


class TelegramNetworkError(TelegramClientError):
    """Raised when Telegram API is unreachable."""


class TelegramRateLimitError(TelegramClientError):
    """Raised when Telegram rate limits the bot."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TelegramApiError(TelegramClientError):
    """Raised for non-retryable Telegram API errors."""


_CURRENT_DIR = Path(__file__).resolve()
_BACKEND_ENV = _CURRENT_DIR.parents[3] / ".env"
_ROOT_ENV = _CURRENT_DIR.parents[4] / ".env"


class TelegramSettings(BaseSettings):
    """Environment-driven configuration for Telegram delivery."""

    model_config = SettingsConfigDict(
        env_prefix="TELEGRAM_",
        env_file=(str(_BACKEND_ENV), str(_ROOT_ENV), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str = Field(min_length=10)
    default_chat_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DEFAULT_CHAT_ID", "CHAT_ID"),
    )
    timeout_seconds: float = Field(default=10.0, ge=1.0)
    max_retries: int = Field(default=3, ge=0)


class TelegramMessagePayload(BaseModel):
    """Validated response data from Telegram API."""

    message_id: int
    chat_id: int | str
    date: datetime
    text: str | None = None
    raw: dict[str, Any]

    @classmethod
    def from_message(cls, message: Message) -> "TelegramMessagePayload":
        if message is None:
            raise TelegramApiError("Telegram returned an empty response.")
        raw = message.to_dict()
        chat_id = message.chat.id if message.chat else raw.get("chat", {}).get("id")
        if message.message_id is None or chat_id is None:
            raise TelegramApiError("Telegram response is missing required fields.")
        return cls(
            message_id=message.message_id,
            chat_id=chat_id,
            date=message.date,
            text=message.text,
            raw=raw,
        )


class TelegramClient:
    """Async Telegram client wrapper with normalized error handling."""

    def __init__(
        self,
        settings: TelegramSettings | None = None,
        logger: Any | None = None,
    ) -> None:
        if settings is None:
            try:
                settings = TelegramSettings()
            except ValidationError as exc:
                raise TelegramConfigError("Telegram settings are invalid.") from exc
        self._settings = settings
        self._logger = logger
        self._bot = Bot(token=self._settings.bot_token, request=self._build_request())

    @property
    def settings(self) -> TelegramSettings:
        return self._settings

    def _build_request(self) -> HTTPXRequest:
        timeout = self._settings.timeout_seconds
        return HTTPXRequest(
            connect_timeout=timeout,
            read_timeout=timeout,
            write_timeout=timeout,
            pool_timeout=timeout,
        )

    @staticmethod
    def validate_chat_id(chat_id: str | int | None) -> str | int:
        if chat_id is None:
            raise TelegramInvalidChatError("Chat id is required.")
        if isinstance(chat_id, int):
            return chat_id
        if isinstance(chat_id, str):
            cleaned = chat_id.strip()
            if cleaned.startswith("@"):
                return cleaned
            if cleaned.isdigit():
                return int(cleaned)
        raise TelegramInvalidChatError("Chat id format is invalid.")

    async def send_message(
        self,
        *,
        chat_id: str | int,
        text: str,
        parse_mode: str | None = None,
        disable_web_page_preview: bool = True,
    ) -> Message:
        if not text or not text.strip():
            raise TelegramPayloadError("Message text cannot be empty.")

        try:
            return await asyncio.wait_for(
                self._bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    disable_web_page_preview=disable_web_page_preview,
                ),
                timeout=self._settings.timeout_seconds,
            )
        except RetryAfter as exc:
            raise TelegramRateLimitError(
                "Telegram rate limit exceeded.", retry_after=exc.retry_after
            ) from exc
        except TimedOut as exc:
            raise TelegramTimeoutError("Telegram request timed out.") from exc
        except NetworkError as exc:
            raise TelegramNetworkError("Telegram network failure.") from exc
        except InvalidToken as exc:
            raise TelegramUnauthorizedError("Telegram bot token is invalid.") from exc
        except Forbidden as exc:
            raise TelegramInvalidChatError("Bot does not have access to the chat.") from exc
        except BadRequest as exc:
            detail = str(exc)
            if _is_invalid_chat_message(detail):
                raise TelegramInvalidChatError("Telegram chat id is invalid.") from exc
            raise TelegramApiError(detail) from exc
        except TelegramError as exc:
            raise TelegramApiError(str(exc)) from exc

    async def get_me(self) -> User:
        try:
            return await asyncio.wait_for(
                self._bot.get_me(),
                timeout=self._settings.timeout_seconds,
            )
        except RetryAfter as exc:
            raise TelegramRateLimitError(
                "Telegram rate limit exceeded.", retry_after=exc.retry_after
            ) from exc
        except TimedOut as exc:
            raise TelegramTimeoutError("Telegram request timed out.") from exc
        except NetworkError as exc:
            raise TelegramNetworkError("Telegram network failure.") from exc
        except InvalidToken as exc:
            raise TelegramUnauthorizedError("Telegram bot token is invalid.") from exc
        except TelegramError as exc:
            raise TelegramApiError(str(exc)) from exc


def _is_invalid_chat_message(detail: str) -> bool:
    lowered = detail.lower()
    return any(
        phrase in lowered
        for phrase in (
            "chat not found",
            "user not found",
            "invalid user id",
            "chat_id",
            "chat id",
        )
    )