from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.services.telegram.telegram_templates import DEFAULT_ALERT_TEMPLATE

_MARKDOWN_V2_SPECIAL_CHARS = r"_*[]()~`>#+-=|{}.!"
_MARKDOWN_V2_PATTERN = re.compile(rf"([\\{re.escape(_MARKDOWN_V2_SPECIAL_CHARS)}])")


class AlertMessageContext(BaseModel):
    """Structured alert data used to generate Telegram-ready messages."""

    model_config = ConfigDict(extra="allow")

    product_name: str
    action: str
    suggested_price_min: float | None = None
    suggested_price_max: float | None = None
    competitor_insight: str | None = None
    opportunity: str | None = None
    confidence: str | None = None
    revenue_opportunity: float | None = None
    product_id: str | None = None
    recommendation_id: str | None = None
    alert_type: str = "product_alert"
    currency: str = Field(default="৳", min_length=1)
    custom_message: str | None = None


def escape_markdown(text: str) -> str:
    """Escape text for Telegram MarkdownV2 parsing."""
    if not text:
        return ""
    return _MARKDOWN_V2_PATTERN.sub(r"\\\1", text)


def format_alert_message(
    context: AlertMessageContext,
    template: str | None = None,
    *,
    markdown_safe: bool = True,
) -> str:
    """Format a Telegram alert message using the configured template."""
    resolved_template = template or DEFAULT_ALERT_TEMPLATE
    suggested_price = _format_price_range(
        context.suggested_price_min, context.suggested_price_max, context.currency
    )
    revenue_opportunity = _format_currency(context.revenue_opportunity, context.currency)

    payload: dict[str, Any] = {
        "product_name": context.product_name,
        "action": context.action,
        "suggested_price": suggested_price,
        "competitor_insight": context.competitor_insight or "N/A",
        "opportunity": context.opportunity or "N/A",
        "confidence": context.confidence or "N/A",
        "revenue_opportunity": revenue_opportunity,
    }

    if markdown_safe:
        payload = {key: escape_markdown(str(value)) for key, value in payload.items()}

    message = resolved_template.format_map(payload)
    if context.custom_message:
        suffix = escape_markdown(context.custom_message) if markdown_safe else context.custom_message
        message = f"{message}\n\n{suffix}"
    return message


def _format_price_range(
    minimum: float | None,
    maximum: float | None,
    currency: str,
) -> str:
    if minimum is None and maximum is None:
        return "N/A"
    if minimum is not None and maximum is not None:
        return f"{currency}{minimum:,.0f}-{maximum:,.0f}"
    value = minimum if minimum is not None else maximum
    return f"{currency}{value:,.0f}"


def _format_currency(value: float | None, currency: str) -> str:
    if value is None:
        return "N/A"
    return f"{currency}{value:,.0f}"