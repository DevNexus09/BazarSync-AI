"""Alert engine for urgency outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Mapping
from uuid import uuid4

from app.recommendations.urgency_rules import AlertConfig, UrgencyEngineConfig, UrgencyResult


class AlertEngineError(Exception):
    """Base error for alert generation failures."""


@dataclass(frozen=True)
class AlertInput:
    urgency_result: UrgencyResult
    product_id: str
    seller_id: str
    product_title: str | None = None
    seller_price: float | None = None
    recommended_price: float | None = None


@dataclass(frozen=True)
class AlertResult:
    alert_id: str
    should_notify: bool
    summary: str
    telegram_payload: dict[str, Any]
    websocket_event: dict[str, Any]
    alert_payload: dict[str, Any]
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "should_notify": self.should_notify,
            "summary": self.summary,
            "telegram_payload": self.telegram_payload,
            "websocket_event": self.websocket_event,
            "alert_payload": self.alert_payload,
            "created_at": self.created_at.isoformat(),
        }


class AlertEngine:
    """Generates alert payloads for Telegram and realtime dashboard updates."""

    def __init__(
        self,
        config: AlertConfig | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config or UrgencyEngineConfig.from_env().alerts
        self._logger = logger or logging.getLogger(__name__)

    def build_alert(self, input_data: AlertInput) -> AlertResult:
        urgency = input_data.urgency_result
        alert_id = str(uuid4())
        should_notify = self._should_notify(urgency)
        summary = self._build_summary(input_data)
        telegram_payload = self._build_telegram_payload(input_data, summary)
        websocket_event = self._build_websocket_event(input_data, alert_id)
        alert_payload = self._build_alert_payload(input_data, alert_id)

        self._logger.info(
            "alert_generated alert_id=%s product_id=%s urgency=%s notify=%s",
            alert_id,
            input_data.product_id,
            urgency.urgency_level,
            should_notify,
        )

        return AlertResult(
            alert_id=alert_id,
            should_notify=should_notify,
            summary=summary,
            telegram_payload=telegram_payload,
            websocket_event=websocket_event,
            alert_payload=alert_payload,
            created_at=datetime.now(timezone.utc),
        )

    async def build_alert_async(self, input_data: AlertInput) -> AlertResult:
        return self.build_alert(input_data)

    def _should_notify(self, urgency: UrgencyResult) -> bool:
        if urgency.urgency_score >= self._config.notify_min_score:
            return True
        levels = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        urgency_level = levels.get(urgency.urgency_level, 1)
        min_level = levels.get(self._config.notify_min_urgency_level, 2)
        return urgency_level >= min_level

    def _build_summary(self, input_data: AlertInput) -> str:
        urgency = input_data.urgency_result
        product_title = input_data.product_title or "Product"
        return (
            f"{product_title}: {urgency.action_type} | "
            f"{urgency.urgency_level} urgency ({urgency.urgency_score}) | "
            f"Confidence {urgency.confidence}."
        )

    def _build_telegram_payload(
        self, input_data: AlertInput, summary: str
    ) -> dict[str, Any]:
        urgency = input_data.urgency_result
        reasoning = self._format_reasoning(urgency.reasoning_summary)
        price_line = ""
        if input_data.seller_price is not None:
            price_line = f"\nCurrent price: {input_data.seller_price:.2f}"
        if input_data.recommended_price is not None:
            price_line += f"\nRecommended price: {input_data.recommended_price:.2f}"

        message = (
            f"{summary}\n"
            f"Action: {urgency.action_type}\n"
            f"Opportunity: {urgency.revenue_opportunity:.2f}\n"
            f"Stock risk: {urgency.stock_risk_level}\n"
            f"Confidence: {urgency.confidence}\n"
            f"{reasoning}{price_line}"
        )
        return {
            "channel": "telegram",
            "text": message,
            "parse_mode": "Markdown",
        }

    def _build_websocket_event(self, input_data: AlertInput, alert_id: str) -> dict[str, Any]:
        urgency = input_data.urgency_result
        return {
            "type": "urgency_alert",
            "event_id": alert_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "product_id": input_data.product_id,
                "seller_id": input_data.seller_id,
                "urgency_score": urgency.urgency_score,
                "urgency_level": urgency.urgency_level,
                "action_type": urgency.action_type,
                "confidence": urgency.confidence,
                "revenue_opportunity": urgency.revenue_opportunity,
                "market_opportunity_score": urgency.market_opportunity_score,
                "reasoning_summary": urgency.reasoning_summary,
                "triggered_rules": urgency.triggered_rules,
            },
        }

    def _build_alert_payload(self, input_data: AlertInput, alert_id: str) -> dict[str, Any]:
        urgency = input_data.urgency_result
        return {
            "alert_id": alert_id,
            "product_id": input_data.product_id,
            "seller_id": input_data.seller_id,
            "action_type": urgency.action_type,
            "urgency_level": urgency.urgency_level,
            "urgency_score": urgency.urgency_score,
            "confidence": urgency.confidence,
            "confidence_score": urgency.confidence_score,
            "stock_risk_level": urgency.stock_risk_level,
            "revenue_opportunity": urgency.revenue_opportunity,
            "market_opportunity_score": urgency.market_opportunity_score,
            "reasoning_summary": urgency.reasoning_summary,
            "triggered_rules": urgency.triggered_rules,
        }

    @staticmethod
    def _format_reasoning(reasoning: str) -> str:
        if not reasoning:
            return "Reasoning: Not available."
        return f"Reasoning: {reasoning}"


EXAMPLE_ALERT_INPUT: dict[str, Any] = {
    "product_id": "DBL200",
    "seller_id": "SELLER-42",
    "product_title": "Dove Body Lotion 200ml",
    "seller_price": 450,
    "recommended_price": 430,
}

EXAMPLE_ALERT_EXPECTED_OUTPUT: dict[str, Any] = {
    "should_notify": True,
    "urgency_level": "HIGH",
}


def build_alert_from_payload(
    payload: Mapping[str, Any],
    *,
    urgency_result: UrgencyResult,
    config: AlertConfig | None = None,
) -> AlertResult:
    input_data = AlertInput(
        urgency_result=urgency_result,
        product_id=str(payload.get("product_id") or payload.get("sku") or "UNKNOWN"),
        seller_id=str(payload.get("seller_id") or payload.get("merchant_id") or "UNKNOWN"),
        product_title=payload.get("product_title"),
        seller_price=_optional_float(payload.get("seller_price")),
        recommended_price=_optional_float(payload.get("recommended_price")),
    )
    engine = AlertEngine(config=config)
    return engine.build_alert(input_data)


if __name__ == "__main__":
    sample_urgency = UrgencyResult(
        urgency_score=78,
        urgency_level="HIGH",
        action_type="PRICE_LOWER",
        confidence="MEDIUM",
        confidence_score=0.58,
        revenue_opportunity=4200.0,
        stock_risk_level="MEDIUM",
        reasoning_summary="High urgency driven by competitor undercutting.",
        triggered_rules=["PRICE_GAP_THRESHOLD"],
        market_opportunity_score=71,
        rule_results=[],
        data_quality=None,
        diagnostics={},
    )
    engine = AlertEngine()
    alert = engine.build_alert(
        AlertInput(
            urgency_result=sample_urgency,
            product_id="DBL200",
            seller_id="SELLER-42",
            product_title="Dove Body Lotion 200ml",
            seller_price=450,
            recommended_price=430,
        )
    )
    print(alert.to_dict())


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
