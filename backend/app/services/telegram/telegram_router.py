from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.async_db import get_async_db
from app.dependencies.auth import get_current_seller_async
from app.models.seller import Seller
from app.schemas.telegram import (
    TelegramConnectTokenResponse,
    TelegramConnectionStatus,
    TelegramDisconnectResponse,
    TelegramHealthResponse,
)
from app.services.telegram.telegram_client import TelegramClient, TelegramClientError, TelegramConfigError
from app.services.telegram.telegram_connection_service import (
    ConnectionNotFoundError,
    TelegramConnectionService,
    TelegramConnectionSettings,
)
from app.services.telegram.telegram_service import TelegramService
from app.services.telegram.telegram_webhook import TelegramWebhookHandler

router = APIRouter(prefix="/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)


@router.post("/connect-token", response_model=TelegramConnectTokenResponse)
async def create_connect_token(
    current_seller: Seller = Depends(get_current_seller_async),
    db: AsyncSession = Depends(get_async_db),
) -> TelegramConnectTokenResponse:
    service = TelegramConnectionService(db, logger=logger)
    token = await service.generate_connect_token(str(current_seller.id))
    return TelegramConnectTokenResponse(
        token=token.token,
        expires_at=token.expires_at,
        bot_username=service.settings.bot_username,
    )


@router.get("/status", response_model=TelegramConnectionStatus)
async def get_connection_status(
    current_seller: Seller = Depends(get_current_seller_async),
    db: AsyncSession = Depends(get_async_db),
) -> TelegramConnectionStatus:
    service = TelegramConnectionService(db, logger=logger)
    connection = await service.get_status(str(current_seller.id))
    return TelegramConnectionStatus(
        is_connected=bool(connection and connection.is_connected),
        connected_at=connection.connected_at if connection else None,
        telegram_username=connection.telegram_username if connection else None,
        telegram_first_name=connection.telegram_first_name if connection else None,
        telegram_last_name=connection.telegram_last_name if connection else None,
        last_alert_sent_at=connection.last_alert_sent_at if connection else None,
        bot_username=service.settings.bot_username,
    )


@router.post("/disconnect", response_model=TelegramDisconnectResponse)
async def disconnect_telegram(
    current_seller: Seller = Depends(get_current_seller_async),
    db: AsyncSession = Depends(get_async_db),
) -> TelegramDisconnectResponse:
    service = TelegramConnectionService(db, logger=logger)
    try:
        await service.disconnect_seller(str(current_seller.id))
    except ConnectionNotFoundError:
        return TelegramDisconnectResponse()
    return TelegramDisconnectResponse()


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> dict[str, str]:
    settings = TelegramConnectionSettings()
    secret = settings.webhook_secret
    if secret:
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if header != secret:
            raise HTTPException(status_code=403, detail="Invalid webhook token.")

    payload = await request.json()
    service = TelegramConnectionService(db, settings=settings, logger=logger)
    handler = TelegramWebhookHandler(service, TelegramService(logger=logger), logger=logger)
    try:
        await handler.handle(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}


@router.get("/health", response_model=TelegramHealthResponse)
async def telegram_health_check() -> TelegramHealthResponse:
    try:
        client = TelegramClient()
        me = await client.get_me()
    except TelegramConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TelegramClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return TelegramHealthResponse(
        status="ok",
        bot_username=me.username,
        bot_id=me.id,
    )
