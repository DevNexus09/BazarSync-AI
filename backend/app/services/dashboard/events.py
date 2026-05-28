from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]


class DashboardEventEmitter(Protocol):
    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        ...


@dataclass(frozen=True)
class NoopEventEmitter:
    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        return None


class DashboardEvent(str):
    recommendation_created = "recommendation_created"
    alert_sent = "alert_sent"
    competitor_updated = "competitor_updated"
    stock_risk_detected = "stock_risk_detected"
