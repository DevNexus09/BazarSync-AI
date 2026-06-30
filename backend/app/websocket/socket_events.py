from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(word.capitalize() for word in parts[1:])


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class RealtimeEventType(str, Enum):
    RECOMMENDATION_CREATED = "recommendation_created"
    ALERT_SENT = "alert_sent"
    PRODUCT_SNAPSHOT_SENT = "product_snapshot_sent"
    COMPETITOR_UPDATED = "competitor_updated"
    STOCK_RISK_DETECTED = "stock_risk_detected"
    URGENCY_SCORE_UPDATED = "urgency_score_updated"
    DASHBOARD_SUMMARY_UPDATED = "dashboard_summary_updated"
    MARKET_OPPORTUNITY_DETECTED = "market_opportunity_detected"
    CONNECTION_ESTABLISHED = "connection_established"
    ROOMS_UPDATED = "rooms_updated"
    SERVER_PONG = "server_pong"
    REALTIME_ERROR = "realtime_error"
    TELEGRAM_CONNECTED = "telegram_connected"
    TELEGRAM_DISCONNECTED = "telegram_disconnected"
    ALERT_FAILED = "alert_failed"
    COMPETITOR_SNAPSHOT_CREATED = "competitor.snapshot.created"
    COMPETITOR_EVENT_CREATED = "competitor.event.created"
    COMPETITOR_RANKINGS_UPDATED = "competitor.rankings.updated"
    MARKET_OPPORTUNITY_CREATED = "market.opportunity.created"
    COMPETITOR_SUMMARY_UPDATED = "competitor.summary.updated"


class RealtimeEventBase(CamelModel):
    event_id: UUID = Field(default_factory=uuid4)
    event: RealtimeEventType
    version: int = 1
    timestamp: datetime = Field(default_factory=_utcnow)
    seller_id: UUID | None = None
    product_id: UUID | None = None


class DashboardRealtimeEnvelope(CamelModel):
    version: int = 1
    event: RealtimeEventType
    seller_id: UUID
    product_id: UUID
    occurred_at: datetime
    data: dict

    model_config = ConfigDict(
        alias_generator=None,
        populate_by_name=True,
        use_enum_values=True,
        extra="forbid",
    )


class RecommendationSnapshot(CamelModel):
    id: UUID
    title: str
    summary: str
    action: str
    status: str
    priority: str
    confidence: float
    expected_lift: float
    product: str
    competitor: str | None = None
    created_at: datetime


class AlertSnapshot(CamelModel):
    id: UUID
    title: str
    message: str
    severity: str
    status: str
    category: str
    channel: str
    product: str | None = None
    competitor: str | None = None
    urgency_score: int
    created_at: datetime


class CompetitorSnapshot(CamelModel):
    id: UUID
    product: str
    competitor: str
    competitor_price: float
    seller_price: float
    price_gap: float
    stock_status: str
    urgency_score: int
    recommendation_action: str
    trend: str
    last_updated: datetime
    status: str


class RecommendationCreatedPayload(CamelModel):
    recommendation: RecommendationSnapshot
    urgency_score: int
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    opportunity_score: float


class AlertSentPayload(CamelModel):
    alert: AlertSnapshot


class ProductSnapshotSentPayload(CamelModel):
    seller_id: UUID
    product_id: UUID
    timestamp: datetime
    product_title: str | None = None


class CompetitorUpdatedPayload(CamelModel):
    competitor: CompetitorSnapshot


class StockRiskDetectedPayload(CamelModel):
    alert: AlertSnapshot
    risk_score: int


class UrgencyScoreUpdatedPayload(CamelModel):
    urgency_score: int
    previous_score: int | None = None
    delta: int | None = None
    updated_at: datetime
    reason: str | None = None


class KpiMetricPayload(CamelModel):
    label: str
    value: str
    delta: str
    trend: str


class InsightPayload(CamelModel):
    id: str
    title: str
    summary: str
    severity: str


class DashboardSummarySnapshot(CamelModel):
    kpis: list[KpiMetricPayload] = Field(default_factory=list)
    insights: list[InsightPayload] = Field(default_factory=list)
    active_alerts: int
    live_competitors: int
    ai_recommendations: int
    revenue_opportunities: int
    urgency_score: int
    system_status: str
    last_synced_at: datetime


class DashboardSummaryPayload(CamelModel):
    summary: DashboardSummarySnapshot


class MarketOpportunitySnapshot(CamelModel):
    id: UUID
    title: str
    description: str
    potential_revenue: float
    probability: float
    urgency_score: int
    time_window: str
    category: str


class MarketOpportunityPayload(CamelModel):
    opportunity: MarketOpportunitySnapshot


class ConnectionEstablishedPayload(CamelModel):
    session_id: str
    sid: str
    rooms: list[str]
    heartbeat_interval: int
    heartbeat_timeout: int


class RoomsUpdatedPayload(CamelModel):
    rooms: list[str]
    action: Literal["joined", "left", "restored"]


class ServerPongPayload(CamelModel):
    client_timestamp: int
    server_timestamp: int
    latency_ms: int | None = None


class RealtimeErrorPayload(CamelModel):
    code: str
    message: str
    details: dict[str, str] | None = None


class TelegramConnectionSnapshot(CamelModel):
    id: UUID
    is_connected: bool
    telegram_username: str | None = None
    telegram_first_name: str | None = None
    telegram_last_name: str | None = None
    connected_at: datetime | None = None
    last_alert_sent_at: datetime | None = None


class TelegramConnectionPayload(CamelModel):
    connection: TelegramConnectionSnapshot


class AlertFailedPayload(CamelModel):
    alert_id: UUID
    status: str
    reason: str | None = None
    telegram_chat_id: str | None = None


class RecommendationCreatedEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.RECOMMENDATION_CREATED
    payload: RecommendationCreatedPayload


class AlertSentEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.ALERT_SENT
    payload: AlertSentPayload


class ProductSnapshotSentEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.PRODUCT_SNAPSHOT_SENT
    payload: ProductSnapshotSentPayload


class CompetitorUpdatedEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.COMPETITOR_UPDATED
    payload: CompetitorUpdatedPayload


class StockRiskDetectedEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.STOCK_RISK_DETECTED
    payload: StockRiskDetectedPayload


class UrgencyScoreUpdatedEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.URGENCY_SCORE_UPDATED
    payload: UrgencyScoreUpdatedPayload


class DashboardSummaryUpdatedEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.DASHBOARD_SUMMARY_UPDATED
    payload: DashboardSummaryPayload


class MarketOpportunityDetectedEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.MARKET_OPPORTUNITY_DETECTED
    payload: MarketOpportunityPayload


class ConnectionEstablishedEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.CONNECTION_ESTABLISHED
    payload: ConnectionEstablishedPayload


class RoomsUpdatedEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.ROOMS_UPDATED
    payload: RoomsUpdatedPayload


class ServerPongEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.SERVER_PONG
    payload: ServerPongPayload


class RealtimeErrorEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.REALTIME_ERROR
    payload: RealtimeErrorPayload


class TelegramConnectedEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.TELEGRAM_CONNECTED
    payload: TelegramConnectionPayload


class TelegramDisconnectedEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.TELEGRAM_DISCONNECTED
    payload: TelegramConnectionPayload


class AlertFailedEvent(RealtimeEventBase):
    event: RealtimeEventType = RealtimeEventType.ALERT_FAILED
    payload: AlertFailedPayload


RealtimeEvent = (
    RecommendationCreatedEvent
    | AlertSentEvent
    | ProductSnapshotSentEvent
    | CompetitorUpdatedEvent
    | StockRiskDetectedEvent
    | UrgencyScoreUpdatedEvent
    | DashboardSummaryUpdatedEvent
    | MarketOpportunityDetectedEvent
    | ConnectionEstablishedEvent
    | RoomsUpdatedEvent
    | ServerPongEvent
    | RealtimeErrorEvent
    | TelegramConnectedEvent
    | TelegramDisconnectedEvent
    | AlertFailedEvent
    | DashboardRealtimeEnvelope
)
