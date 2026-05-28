"""Alert API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.telegram.telegram_client import (
    TelegramApiError,
    TelegramConfigError,
    TelegramInvalidChatError,
    TelegramNetworkError,
    TelegramPayloadError,
    TelegramRateLimitError,
    TelegramTimeoutError,
    TelegramUnauthorizedError,
)
from app.services.telegram.telegram_formatter import AlertMessageContext
from app.services.telegram.telegram_service import TelegramDeliveryResult, TelegramService

router = APIRouter(prefix="/alerts", tags=["alerts"])


class TelegramTestAlertRequest(BaseModel):
    chat_id: int | str | None = None
    product_name: str = Field(default="BazarSync Demo Product")
    action: str = Field(default="Lower price by 3%")
    suggested_price_min: float | None = 1200
    suggested_price_max: float | None = 1350
    competitor_insight: str = Field(
        default="Competitor dropped price by 5% in the last 24 hours."
    )
    opportunity: str = Field(default="Regain buy box and boost conversion.")
    confidence: str = Field(default="High")
    revenue_opportunity: float | None = 3200
    currency: str = Field(default="BDT", min_length=1)
    custom_message: str | None = Field(default="Test alert generated from /alerts/test.")


@router.post("/test", response_model=TelegramDeliveryResult)
async def send_test_alert(
    payload: TelegramTestAlertRequest | None = None,
) -> TelegramDeliveryResult:
    payload = payload or TelegramTestAlertRequest()
    try:
        service = TelegramService(logger=logging.getLogger("app.telegram.test"))
    except TelegramConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    alert = AlertMessageContext(
        product_name=payload.product_name,
        action=payload.action,
        suggested_price_min=payload.suggested_price_min,
        suggested_price_max=payload.suggested_price_max,
        competitor_insight=payload.competitor_insight,
        opportunity=payload.opportunity,
        confidence=payload.confidence,
        revenue_opportunity=payload.revenue_opportunity,
        currency=payload.currency,
        custom_message=payload.custom_message,
        alert_type="test_alert",
    )
    try:
        return await service.send_alert_message(alert, chat_id=payload.chat_id)
    except TelegramRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (TelegramInvalidChatError, TelegramPayloadError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TelegramUnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (TelegramTimeoutError, TelegramNetworkError, TelegramApiError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except TelegramConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
