from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TelegramConnectTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    expires_at: datetime
    bot_username: str | None = None


class TelegramConnectionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_connected: bool
    connected_at: datetime | None = None
    telegram_username: str | None = None
    telegram_first_name: str | None = None
    telegram_last_name: str | None = None
    last_alert_sent_at: datetime | None = None
    bot_username: str | None = None


class TelegramDisconnectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="disconnected")


class TelegramHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    bot_username: str | None = None
    bot_id: int | None = None
