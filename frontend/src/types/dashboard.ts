export type KpiTrend = "up" | "down" | "flat"

export type KpiMetric = {
  label: string
  value: string
  delta: string
  trend: KpiTrend
}

export type Insight = {
  id: string
  title: string
  summary: string
  severity: "low" | "medium" | "high"
}

export type DashboardSummary = {
  kpis: KpiMetric[]
  insights: Insight[]
}
