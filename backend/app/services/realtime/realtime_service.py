from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Protocol
from uuid import UUID, uuid4

from app.websocket.socket_events import (
    AlertFailedEvent,
    AlertFailedPayload,
    AlertSentEvent,
    AlertSentPayload,
    AlertSnapshot,
    CompetitorUpdatedEvent,
    CompetitorUpdatedPayload,
    CompetitorSnapshot,
    DashboardSummaryPayload,
    DashboardSummarySnapshot,
    DashboardSummaryUpdatedEvent,
    MarketOpportunityDetectedEvent,
    MarketOpportunityPayload,
    MarketOpportunitySnapshot,
    RecommendationCreatedEvent,
    RecommendationCreatedPayload,
    RecommendationSnapshot,
    StockRiskDetectedEvent,
    StockRiskDetectedPayload,
    UrgencyScoreUpdatedEvent,
    UrgencyScoreUpdatedPayload,
    RealtimeEvent,
)
from app.websocket.socket_rooms import (
    ACTIVITY_ROOM,
    ALERTS_ROOM,
    DASHBOARD_ROOM,
    product_room,
    seller_room,
)


class RealtimeEmitter(Protocol):
    async def emit_event(self, event: RealtimeEvent, *, rooms: Iterable[str] | None = None) -> None: ...


class RealtimeService:
    """High-level realtime emitters for the War Room dashboard."""

    def __init__(self, emitter: RealtimeEmitter, logger: logging.Logger | None = None) -> None:
        self._emitter = emitter
        self._logger = logger or logging.getLogger(__name__)

    async def emit_recommendation_created(
        self,
        payload: RecommendationCreatedPayload,
        *,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
        rooms: Iterable[str] | None = None,
    ) -> None:
        event = RecommendationCreatedEvent(
            payload=payload,
            seller_id=seller_id,
            product_id=product_id,
        )
        await self._emit(event, rooms=rooms)

    async def emit_alert_sent(
        self,
        payload: AlertSentPayload,
        *,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
        rooms: Iterable[str] | None = None,
    ) -> None:
        event = AlertSentEvent(payload=payload, seller_id=seller_id, product_id=product_id)
        await self._emit(event, rooms=rooms or self._default_alert_rooms(seller_id, product_id))

    async def emit_alert_failed(
        self,
        payload: AlertFailedPayload,
        *,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
        rooms: Iterable[str] | None = None,
    ) -> None:
        event = AlertFailedEvent(payload=payload, seller_id=seller_id, product_id=product_id)
        await self._emit(event, rooms=rooms or self._default_alert_rooms(seller_id, product_id))

    async def emit_competitor_updated(
        self,
        payload: CompetitorUpdatedPayload,
        *,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
        rooms: Iterable[str] | None = None,
    ) -> None:
        event = CompetitorUpdatedEvent(
            payload=payload,
            seller_id=seller_id,
            product_id=product_id,
        )
        await self._emit(event, rooms=rooms)

    async def emit_stock_risk_detected(
        self,
        payload: StockRiskDetectedPayload,
        *,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
        rooms: Iterable[str] | None = None,
    ) -> None:
        event = StockRiskDetectedEvent(
            payload=payload,
            seller_id=seller_id,
            product_id=product_id,
        )
        await self._emit(event, rooms=rooms or self._default_alert_rooms(seller_id, product_id))

    async def emit_urgency_score_updated(
        self,
        payload: UrgencyScoreUpdatedPayload,
        *,
        seller_id: UUID | None = None,
        rooms: Iterable[str] | None = None,
    ) -> None:
        event = UrgencyScoreUpdatedEvent(payload=payload, seller_id=seller_id)
        await self._emit(event, rooms=rooms or self._default_dashboard_rooms(seller_id, None))

    async def emit_dashboard_summary_updated(
        self,
        payload: DashboardSummaryPayload,
        *,
        seller_id: UUID | None = None,
        rooms: Iterable[str] | None = None,
    ) -> None:
        event = DashboardSummaryUpdatedEvent(payload=payload, seller_id=seller_id)
        await self._emit(event, rooms=rooms or self._default_dashboard_rooms(seller_id, None))

    async def emit_market_opportunity_detected(
        self,
        payload: MarketOpportunityPayload,
        *,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
        rooms: Iterable[str] | None = None,
    ) -> None:
        event = MarketOpportunityDetectedEvent(
            payload=payload,
            seller_id=seller_id,
            product_id=product_id,
        )
        await self._emit(event, rooms=rooms)

    @staticmethod
    def example_payloads() -> dict[str, object]:
        now = datetime.now(timezone.utc)
        return {
            "recommendation_created": RecommendationCreatedPayload(
                recommendation=RecommendationSnapshot(
                    id=uuid4(),
                    title="Win back buy box",
                    summary="Lower price by 4% to regain buy box.",
                    action="undercut",
                    status="new",
                    priority="high",
                    confidence=0.82,
                    expected_lift=0.18,
                    product="SKU-9911",
                    competitor="Daraz",
                    created_at=now,
                ),
                urgency_score=82,
                confidence="HIGH",
                opportunity_score=4200,
            ),
            "alert_sent": AlertSentPayload(
                alert=AlertSnapshot(
                    id=uuid4(),
                    title="Stock risk detected",
                    message="Competitor stock moved below 10 units.",
                    severity="critical",
                    status="new",
                    category="stock_risk",
                    channel="dashboard",
                    urgency_score=91,
                    created_at=now,
                    product="SKU-9911",
                    competitor="Daraz",
                )
            ),
            "competitor_updated": CompetitorUpdatedPayload(
                competitor=CompetitorSnapshot(
                    id=uuid4(),
                    product="SKU-9911",
                    competitor="Daraz",
                    competitor_price=14.2,
                    seller_price=15.9,
                    price_gap=-1.7,
                    stock_status="low_stock",
                    urgency_score=78,
                    recommendation_action="undercut",
                    trend="down",
                    last_updated=now,
                    status="active",
                )
            ),
            "stock_risk_detected": StockRiskDetectedPayload(
                alert=AlertSnapshot(
                    id=uuid4(),
                    title="Stock risk detected",
                    message="Competitor inventory dropped below safety threshold.",
                    severity="critical",
                    status="new",
                    category="stock_risk",
                    channel="dashboard",
                    urgency_score=88,
                    created_at=now,
                    product="SKU-9911",
                    competitor="Daraz",
                ),
                risk_score=88,
            ),
            "urgency_score_updated": UrgencyScoreUpdatedPayload(
                urgency_score=74,
                previous_score=68,
                delta=6,
                updated_at=now,
                reason="Competitor price dropped 3%.",
            ),
            "dashboard_summary_updated": DashboardSummaryPayload(
                summary=DashboardSummarySnapshot(
                    kpis=[],
                    insights=[],
                    active_alerts=5,
                    live_competitors=24,
                    ai_recommendations=12,
                    revenue_opportunities=9,
                    urgency_score=74,
                    system_status="healthy",
                    last_synced_at=now,
                )
            ),
            "market_opportunity_detected": MarketOpportunityPayload(
                opportunity=MarketOpportunitySnapshot(
                    id=uuid4(),
                    title="Weekend demand spike",
                    description="Category demand is trending upward.",
                    potential_revenue=12000,
                    probability=0.64,
                    urgency_score=71,
                    time_window="48h",
                    category="promotion",
                )
            ),
        }

    async def _emit(
        self,
        event: RecommendationCreatedEvent
        | AlertSentEvent
        | AlertFailedEvent
        | CompetitorUpdatedEvent
        | StockRiskDetectedEvent
        | UrgencyScoreUpdatedEvent
        | DashboardSummaryUpdatedEvent
        | MarketOpportunityDetectedEvent,
        *,
        rooms: Iterable[str] | None = None,
    ) -> None:
        await self._emitter.emit_event(event, rooms=rooms or self._default_rooms(event))

    def _default_rooms(
        self,
        event: RecommendationCreatedEvent
        | AlertSentEvent
        | AlertFailedEvent
        | CompetitorUpdatedEvent
        | StockRiskDetectedEvent
        | UrgencyScoreUpdatedEvent
        | DashboardSummaryUpdatedEvent
        | MarketOpportunityDetectedEvent,
    ) -> set[str]:
        if isinstance(event, (AlertSentEvent, AlertFailedEvent, StockRiskDetectedEvent)):
            return self._default_alert_rooms(event.seller_id, event.product_id)
        if isinstance(event, (UrgencyScoreUpdatedEvent, DashboardSummaryUpdatedEvent)):
            return self._default_dashboard_rooms(event.seller_id, event.product_id)
        return self._default_dashboard_rooms(event.seller_id, event.product_id)

    def _default_dashboard_rooms(
        self, seller_id: UUID | None, product_id: UUID | None
    ) -> set[str]:
        rooms: set[str] = set()
        if seller_id is None:
            rooms.update({DASHBOARD_ROOM, ACTIVITY_ROOM})
        if seller_id:
            rooms.add(seller_room(str(seller_id)))
        if product_id:
            rooms.add(product_room(str(product_id)))
        return rooms

    def _default_alert_rooms(
        self, seller_id: UUID | None, product_id: UUID | None
    ) -> set[str]:
        rooms: set[str] = set()
        if seller_id is None:
            rooms.update({ALERTS_ROOM, ACTIVITY_ROOM, DASHBOARD_ROOM})
        if seller_id:
            rooms.add(seller_room(str(seller_id)))
        if product_id:
            rooms.add(product_room(str(product_id)))
        return rooms
