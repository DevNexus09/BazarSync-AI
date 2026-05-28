export const AlertSeverity = {
  Low: "low",
  Medium: "medium",
  High: "high",
  Critical: "critical",
} as const

export type AlertSeverity = (typeof AlertSeverity)[keyof typeof AlertSeverity]

export const AlertStatus = {
  New: "new",
  Acknowledged: "acknowledged",
  Resolved: "resolved",
} as const

export type AlertStatus = (typeof AlertStatus)[keyof typeof AlertStatus]

export const AlertCategory = {
  StockRisk: "stock_risk",
  PriceWar: "price_war",
  CompetitorMove: "competitor_move",
  Opportunity: "opportunity",
  System: "system",
} as const

export type AlertCategory = (typeof AlertCategory)[keyof typeof AlertCategory]

export const AlertChannel = {
  Telegram: "telegram",
  Dashboard: "dashboard",
  Email: "email",
} as const

export type AlertChannel = (typeof AlertChannel)[keyof typeof AlertChannel]

export type Alert = {
  id: string
  title: string
  message: string
  severity: AlertSeverity
  status: AlertStatus
  category: AlertCategory
  channel: AlertChannel
  product?: string | null
  competitor?: string | null
  urgencyScore: number
  createdAt: string
}

export type AlertSummary = {
  activeCount: number
  criticalCount: number
  lastTriggeredAt: string | null
}