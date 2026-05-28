export const KpiTrend = {
  Up: "up",
  Down: "down",
  Flat: "flat",
} as const

export type KpiTrend = (typeof KpiTrend)[keyof typeof KpiTrend]

export const SystemStatus = {
  Healthy: "healthy",
  Degraded: "degraded",
  Offline: "offline",
} as const

export type SystemStatus = (typeof SystemStatus)[keyof typeof SystemStatus]

export type KpiMetric = {
  label: string
  value: string
  delta: string
  trend: KpiTrend
}

export type InsightSeverity = "low" | "medium" | "high"

export type Insight = {
  id: string
  title: string
  summary: string
  severity: InsightSeverity
}

export type DashboardSummary = {
  kpis: KpiMetric[]
  insights: Insight[]
  activeAlerts: number
  liveCompetitors: number
  aiRecommendations: number
  revenueOpportunities: number
  urgencyScore: number
  systemStatus: SystemStatus
  lastSyncedAt: string
}

export type MarketTrendPoint = {
  timestamp: string
  demandIndex: number
  urgencyIndex: number
  opportunityIndex: number
  priceIndex: number
}

export type OpportunityMetric = {
  id: string
  label: string
  value: string
  delta: string
  trend: KpiTrend
}

export type MarketOpportunity = {
  id: string
  title: string
  description: string
  potentialRevenue: number
  probability: number
  urgencyScore: number
  timeWindow: string
  category: "pricing" | "inventory" | "promotion" | "expansion"
}

export const ActivitySeverity = {
  Info: "info",
  Warning: "warning",
  Critical: "critical",
} as const

export type ActivitySeverity =
  (typeof ActivitySeverity)[keyof typeof ActivitySeverity]

export type ActivityItem = {
  id: string
  title: string
  description: string
  timestamp: string
  category: "recommendation" | "alert" | "competitor" | "system"
  severity: ActivitySeverity
}

export type RealtimeStatus = {
  connected: boolean
  reconnecting: boolean
  lastEventAt: string | null
  transport?: string
  latencyMs?: number | null
  sessionId?: string
  rooms?: string[]
  lastError?: string
}

export type StockRiskEvent = {
  alertId: string
  product: string
  competitor?: string | null
  riskScore: number
  message: string
  createdAt: string
}

export type SystemStatusUpdate = {
  status: SystemStatus
  message: string
  updatedAt: string
}
