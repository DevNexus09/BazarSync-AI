import type { Alert } from "@/types/alert"
import type { Competitor } from "@/types/competitor"
import type { DashboardSummary, MarketOpportunity } from "@/types/dashboard"
import type { Recommendation } from "@/types/recommendation"

export const RealtimeEventName = {
  RecommendationCreated: "recommendation_created",
  AlertSent: "alert_sent",
  ProductSnapshotSent: "product_snapshot_sent",
  AlertFailed: "alert_failed",
  CompetitorUpdated: "competitor_updated",
  StockRiskDetected: "stock_risk_detected",
  UrgencyScoreUpdated: "urgency_score_updated",
  DashboardSummaryUpdated: "dashboard_summary_updated",
  MarketOpportunityDetected: "market_opportunity_detected",
  TelegramConnected: "telegram_connected",
  TelegramDisconnected: "telegram_disconnected",
  ConnectionEstablished: "connection_established",
  RoomsUpdated: "rooms_updated",
  ServerPong: "server_pong",
  RealtimeError: "realtime_error",
} as const

export type RealtimeEventName =
  (typeof RealtimeEventName)[keyof typeof RealtimeEventName]

export type RealtimeEventEnvelope<TEvent extends RealtimeEventName, TPayload> = {
  event: TEvent
  eventId: string
  version: number
  timestamp: string
  sellerId?: string | null
  productId?: string | null
  payload: TPayload
}

export type RecommendationCreatedPayload = {
  recommendation: Recommendation
  urgencyScore: number
  confidence: "LOW" | "MEDIUM" | "HIGH"
  opportunityScore: number
}

export type AlertSentPayload = {
  alert: Alert
}

export type ProductSnapshotSentPayload = {
  sellerId: string
  productId: string
  timestamp: string
  productTitle?: string | null
}

export type AlertFailedPayload = {
  alertId: string
  status: string
  reason?: string | null
  telegramChatId?: string | null
}

export type CompetitorUpdatedPayload = {
  competitor: Competitor
}

export type StockRiskDetectedPayload = {
  alert: Alert
  riskScore: number
}

export type UrgencyScoreUpdatedPayload = {
  urgencyScore: number
  previousScore?: number | null
  delta?: number | null
  updatedAt: string
  reason?: string | null
}

export type DashboardSummaryUpdatedPayload = {
  summary: DashboardSummary
}

export type MarketOpportunityDetectedPayload = {
  opportunity: MarketOpportunity
}

export type TelegramConnectionSnapshot = {
  id: string
  isConnected: boolean
  telegramUsername?: string | null
  telegramFirstName?: string | null
  telegramLastName?: string | null
  connectedAt?: string | null
  lastAlertSentAt?: string | null
}

export type TelegramConnectionPayload = {
  connection: TelegramConnectionSnapshot
}

export type ConnectionEstablishedPayload = {
  sessionId: string
  sid: string
  rooms: string[]
  heartbeatInterval: number
  heartbeatTimeout: number
}

export type RoomsUpdatedPayload = {
  rooms: string[]
  action: "joined" | "left" | "restored"
}

export type ServerPongPayload = {
  clientTimestamp: number
  serverTimestamp: number
  latencyMs?: number | null
}

export type RealtimeErrorPayload = {
  code: string
  message: string
  details?: Record<string, string>
}

export type RecommendationCreatedEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.RecommendationCreated,
  RecommendationCreatedPayload
>
export type AlertSentEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.AlertSent,
  AlertSentPayload
>
export type ProductSnapshotSentEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.ProductSnapshotSent,
  ProductSnapshotSentPayload
>
export type AlertFailedEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.AlertFailed,
  AlertFailedPayload
>
export type CompetitorUpdatedEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.CompetitorUpdated,
  CompetitorUpdatedPayload
>
export type StockRiskDetectedEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.StockRiskDetected,
  StockRiskDetectedPayload
>
export type UrgencyScoreUpdatedEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.UrgencyScoreUpdated,
  UrgencyScoreUpdatedPayload
>
export type DashboardSummaryUpdatedEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.DashboardSummaryUpdated,
  DashboardSummaryUpdatedPayload
>
export type MarketOpportunityDetectedEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.MarketOpportunityDetected,
  MarketOpportunityDetectedPayload
>
export type TelegramConnectedEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.TelegramConnected,
  TelegramConnectionPayload
>
export type TelegramDisconnectedEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.TelegramDisconnected,
  TelegramConnectionPayload
>
export type ConnectionEstablishedEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.ConnectionEstablished,
  ConnectionEstablishedPayload
>
export type RoomsUpdatedEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.RoomsUpdated,
  RoomsUpdatedPayload
>
export type ServerPongEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.ServerPong,
  ServerPongPayload
>
export type RealtimeErrorEvent = RealtimeEventEnvelope<
  typeof RealtimeEventName.RealtimeError,
  RealtimeErrorPayload
>

export type RealtimeRoomScope =
  | "seller"
  | "product"
  | "alerts"
  | "dashboard"
  | "activity"
  | "custom"

export type RealtimeRoomTarget = {
  scope: RealtimeRoomScope
  id?: string
}

export type RoomSubscriptionRequest = {
  rooms: RealtimeRoomTarget[]
}

export type RealtimeServerEvents = {
  [RealtimeEventName.RecommendationCreated]: (
    payload: RecommendationCreatedEvent
  ) => void
  [RealtimeEventName.AlertSent]: (payload: AlertSentEvent) => void
  [RealtimeEventName.ProductSnapshotSent]: (
    payload: ProductSnapshotSentEvent
  ) => void
  [RealtimeEventName.AlertFailed]: (payload: AlertFailedEvent) => void
  [RealtimeEventName.CompetitorUpdated]: (
    payload: CompetitorUpdatedEvent
  ) => void
  [RealtimeEventName.StockRiskDetected]: (
    payload: StockRiskDetectedEvent
  ) => void
  [RealtimeEventName.UrgencyScoreUpdated]: (
    payload: UrgencyScoreUpdatedEvent
  ) => void
  [RealtimeEventName.DashboardSummaryUpdated]: (
    payload: DashboardSummaryUpdatedEvent
  ) => void
  [RealtimeEventName.MarketOpportunityDetected]: (
    payload: MarketOpportunityDetectedEvent
  ) => void
  [RealtimeEventName.TelegramConnected]: (payload: TelegramConnectedEvent) => void
  [RealtimeEventName.TelegramDisconnected]: (
    payload: TelegramDisconnectedEvent
  ) => void
  [RealtimeEventName.ConnectionEstablished]: (
    payload: ConnectionEstablishedEvent
  ) => void
  [RealtimeEventName.RoomsUpdated]: (payload: RoomsUpdatedEvent) => void
  [RealtimeEventName.ServerPong]: (payload: ServerPongEvent) => void
  [RealtimeEventName.RealtimeError]: (payload: RealtimeErrorEvent) => void
}

export type RealtimeClientEvents = {
  subscribe_rooms: (payload: RoomSubscriptionRequest) => void
  unsubscribe_rooms: (payload: RoomSubscriptionRequest) => void
  subscribe_war_room: (payload: { scope: "seller"; sellerId?: string }) => void
  client_ping: (payload: { timestamp: number }) => void
}
