from __future__ import annotations

from typing import Mapping

DEFAULT_ALERT_TEMPLATE_KEY = "product_alert"

DEFAULT_ALERT_TEMPLATE = (
    "🚨 BazarSync Product Alert\n\n"
    "📦 Product: {product_name}\n\n"
    "⚡ Action: {action}\n\n"
    "💰 Suggested Price: {suggested_price}\n\n"
    "📊 Competitor Insight:\n{competitor_insight}\n\n"
    "🎯 Opportunity:\n{opportunity}\n\n"
    "📈 Confidence: {confidence}\n\n"
    "💵 Revenue Opportunity: {revenue_opportunity}\n"
)

ALERT_TEMPLATES: Mapping[str, str] = {
    DEFAULT_ALERT_TEMPLATE_KEY: DEFAULT_ALERT_TEMPLATE,
}


def get_template(key: str | None) -> str:
    if not key:
        return DEFAULT_ALERT_TEMPLATE
    return ALERT_TEMPLATES.get(key, DEFAULT_ALERT_TEMPLATE)