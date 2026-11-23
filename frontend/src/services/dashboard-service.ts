import apiClient from "@/api/client"
import { formatCurrency, formatNumber, formatPercent } from "@/utils/formatters"
import { KpiTrend, SystemStatus } from "@/types/dashboard"
import {
  CompetitorStatus,
  CompetitorTrend,
  StockStatus,
} from "@/types/competitor"
import {
  RecommendationAction,
  RecommendationPriority,
  RecommendationStatus,
} from "@/types/recommendation"
import type {
  ActivityItem,
  DashboardSummary,
  Insight,
  MarketOpportunity,
  MarketTrendPoint,
  OpportunityMetric,
} from "@/types/dashboard"
import type { Competitor, CompetitorPricePoint } from "@/types/competitor"
import type { Recommendation } from "@/types/recommendation"

type PaginationMeta = {
  total: number
  page: number
  page_size: number
  total_pages: number
  has_next: boolean
  has_prev: boolean
}

type PaginatedResponse<T> = {
  items: T[]
  meta: PaginationMeta
}

type ApiDashboardSummary = {
  total_monitored_products: number
  active_alerts: number
  opportunity_count: number
  high_risk_stock_count: number
  average_urgency_score: number
  average_competitor_price_gap: number
  market_trend_summary: string
  realtime_activity: {
    recommendations_last_hour: number
    alerts_last_hour: number
    competitor_updates_last_hour: number
    stock_risk_events_last_hour: number
  }
  generated_at: string
}

type ApiRecommendationRecord = {
  recommendation_id: string
  product_title: string
  action_type: string
  confidence: string
  urgency_score?: number | null
  price_gap_percent?: number | null
  stock_risk_score?: number | null
  reasoning?: string | null
  revenue_opportunity?: number | null
  created_at: string
}

type ApiCompetitorRecord = {
  competitor_id: string
  product_title: string
  competitor_title: string
  competitor_price?: number | null
  seller_price?: number | null
  price_gap_percent?: number | null
  stock_status?: string | null
  price_trend?: string | null
  created_at: string
}

type ApiOpportunityRecord = {
  recommendation_id: string
  product_title: string
  revenue_opportunity?: number | null
  inventory_capture_units?: number | null
  projected_demand_shift?: number | null
  estimated_profit_impact?: number | null
  competitor_oos_ratio?: number | null
  market_opportunity_score?: number | null
  created_at: string
}

const mapSystemStatus = (summary: ApiDashboardSummary): SystemStatus => {
  if (summary.high_risk_stock_count > 0 || summary.active_alerts > 0) {
    return SystemStatus.Degraded
  }
  return SystemStatus.Healthy
}

const buildInsights = (summary: ApiDashboardSummary): Insight[] => {
  const insights: Insight[] = []
  if (summary.market_trend_summary) {
    const severity: Insight["severity"] =
      summary.average_urgency_score >= 75
        ? "high"
        : summary.average_urgency_score >= 55
          ? "medium"
          : "low"
    insights.push({
      id: "market-trend",
      title: "Market trend",
      summary: summary.market_trend_summary,
      severity,
    })
  }
  const activity = summary.realtime_activity
  if (activity) {
    insights.push({
      id: "realtime-activity",
      title: "Last hour activity",
      summary: `Recommendations ${activity.recommendations_last_hour}, alerts ${activity.alerts_last_hour}, competitor updates ${activity.competitor_updates_last_hour}.`,
      severity: "low",
    })
  }
  return insights
}

const mapRecommendationAction = (action: string): RecommendationAction => {
  switch (action?.toUpperCase()) {
    case "LOWER":
      return RecommendationAction.Undercut
    case "RAISE":
      return RecommendationAction.RaisePrice
    case "REORDER":
      return RecommendationAction.Restock
    case "HOLD":
    default:
      return RecommendationAction.Hold
  }
}

const mapRecommendationPriority = (
  urgencyScore?: number | null
): RecommendationPriority => {
  const score = urgencyScore ?? 0
  if (score >= 80) return RecommendationPriority.Critical
  if (score >= 60) return RecommendationPriority.High
  if (score >= 40) return RecommendationPriority.Medium
  return RecommendationPriority.Low
}

const mapRecommendationConfidence = (confidence: string): number => {
  switch (confidence?.toUpperCase()) {
    case "HIGH":
      return 0.9
    case "MEDIUM":
      return 0.7
    case "LOW":
      return 0.5
    default:
      return 0.6
  }
}

const recommendationConfidenceLabel = (confidence: string): Recommendation["confidenceLabel"] => {
  const label = confidence.toUpperCase()
  return label === "LOW" || label === "MEDIUM" || label === "HIGH" ? label : undefined
}

const formatRecommendationTitle = (actionType: string) => {
  switch (actionType?.toUpperCase()) {
    case "LOWER":
      return "Lower price recommendation"
    case "RAISE":
      return "Raise price recommendation"
    case "REORDER":
      return "Restock recommendation"
    default:
      return "Hold price recommendation"
  }
}

const mapStockStatus = (status?: string | null): StockStatus => {
  switch (status) {
    case "out_of_stock":
      return StockStatus.OutOfStock
    case "low_stock":
      return StockStatus.LowStock
    default:
      return StockStatus.InStock
  }
}

const mapCompetitorTrend = (trend?: string | null): CompetitorTrend => {
  switch (trend) {
    case "down":
      return CompetitorTrend.Down
    case "up":
      return CompetitorTrend.Up
    default:
      return CompetitorTrend.Flat
  }
}

const mapCompetitorStatus = (): CompetitorStatus => CompetitorStatus.Active

const toNumber = (value?: number | null) => (value == null ? 0 : Number(value))

const computeCompetitorUrgencyScore = (
  priceGapPercent?: number | null,
  stockStatus?: string | null
) => {
  const base = Math.min(Math.abs(priceGapPercent ?? 0) * 2, 100)
  if (stockStatus === "out_of_stock") {
    return Math.max(base, 85)
  }
  if (stockStatus === "low_stock") {
    return Math.max(base, 65)
  }
  return Math.round(base)
}

const resolveRecommendationActionLabel = (
  sellerPrice?: number | null,
  competitorPrice?: number | null
) => {
  if (sellerPrice == null || competitorPrice == null) {
    return "Hold"
  }
  if (sellerPrice > competitorPrice) {
    return "Lower price"
  }
  if (sellerPrice < competitorPrice) {
    return "Raise price"
  }
  return "Hold"
}

const resolveOpportunityCategory = (
  record: ApiOpportunityRecord
): MarketOpportunity["category"] => {
  const oosRatio = record.competitor_oos_ratio ?? 0
  const demandShift = record.projected_demand_shift ?? 0
  if (oosRatio >= 0.5) {
    return "inventory"
  }
  if (demandShift >= 15) {
    return "promotion"
  }
  return "pricing"
}

const buildOpportunityDescription = (record: ApiOpportunityRecord) => {
  const units = Math.round(record.inventory_capture_units ?? 0)
  const profitImpact = Math.round(record.estimated_profit_impact ?? 0)
  return `Capture ${units} units, est. profit impact ${profitImpact}`
}

const buildOpportunityTimeWindow = (createdAt: string) => {
  if (!createdAt) {
    return "Rolling"
  }
  return new Date(createdAt).toLocaleDateString()
}

export async function getDashboardSummary(
  signal?: AbortSignal
): Promise<DashboardSummary> {
  const { data } = await apiClient.get<ApiDashboardSummary>("/dashboard/summary", {
    signal,
  })
  return {
    kpis: [],
    insights: buildInsights(data),
    activeAlerts: data.active_alerts,
    liveCompetitors: data.total_monitored_products,
    aiRecommendations: data.realtime_activity.recommendations_last_hour,
    revenueOpportunities: data.opportunity_count,
    urgencyScore: data.average_urgency_score,
    systemStatus: mapSystemStatus(data),
    lastSyncedAt: data.generated_at,
  }
}

type ApiMarketTrendPoint = {
  timestamp: string
  demand_index: number
  urgency_index: number
  opportunity_index: number
  price_index: number
}

export async function getMarketTrends(
  signal?: AbortSignal
): Promise<MarketTrendPoint[]> {
  const { data } = await apiClient.get<ApiMarketTrendPoint[]>(
    "/dashboard/market-trends",
    { signal }
  )
  return data.map((point) => ({
    timestamp: point.timestamp,
    demandIndex: point.demand_index,
    urgencyIndex: point.urgency_index,
    opportunityIndex: point.opportunity_index,
    priceIndex: point.price_index,
  }))
}

type ApiOpportunityMetric = {
  id: string
  label: string
  value: number | string
  delta: number | string | null
  trend: string
}

const formatMetricNumber = (id: string, value: number) => {
  if (id === "revenue-opportunity") return formatCurrency(value)
  if (id === "confidence") return formatPercent(value)
  return formatNumber(value)
}

export function mapOpportunityMetric(
  metric: ApiOpportunityMetric
): OpportunityMetric {
  const { id, delta, value } = metric
  let deltaLabel: string
  if (delta == null) deltaLabel = "No prior signal"
  else if (typeof delta === "string") deltaLabel = delta
  else deltaLabel = `${delta > 0 ? "+" : ""}${formatMetricNumber(id, delta)}`
  return {
    id,
    label: metric.label,
    value: typeof value === "number" ? formatMetricNumber(id, value) : value,
    delta: deltaLabel,
    trend:
      metric.trend === KpiTrend.Up || metric.trend === KpiTrend.Down
        ? metric.trend
        : KpiTrend.Flat,
  }
}

export async function getOpportunityMetrics(
  signal?: AbortSignal
): Promise<OpportunityMetric[]> {
  const { data } = await apiClient.get<ApiOpportunityMetric[]>(
    "/dashboard/opportunity-metrics",
    { signal }
  )
  return data.map(mapOpportunityMetric)
}

export async function getMarketOpportunities(
  signal?: AbortSignal
): Promise<MarketOpportunity[]> {
  const { data } = await apiClient.get<PaginatedResponse<ApiOpportunityRecord>>(
    "/dashboard/market-opportunities",
    { signal }
  )
  return data.items.map((opportunity) => ({
    id: opportunity.recommendation_id,
    title: opportunity.product_title,
    description: buildOpportunityDescription(opportunity),
    potentialRevenue: toNumber(opportunity.revenue_opportunity),
    probability: opportunity.competitor_oos_ratio ?? 0,
    urgencyScore: Math.min(
      Math.max(Math.round(opportunity.market_opportunity_score ?? 0), 0),
      100
    ),
    timeWindow: buildOpportunityTimeWindow(opportunity.created_at),
    category: resolveOpportunityCategory(opportunity),
  }))
}

export async function getActivityFeed(
  signal?: AbortSignal
): Promise<ActivityItem[]> {
  // Backend fields already match the frontend shape.
  const { data } = await apiClient.get<ActivityItem[]>("/dashboard/activity", {
    signal,
  })
  return data
}

export async function getRecommendations(
  signal?: AbortSignal
): Promise<Recommendation[]> {
  const { data } = await apiClient.get<PaginatedResponse<ApiRecommendationRecord>>(
    "/dashboard/recommendations",
    { signal, params: { sort_by: "urgency_score", page_size: 3 } }
  )
  return data.items.map((rec) => ({
    id: rec.recommendation_id,
    title: formatRecommendationTitle(rec.action_type),
    summary: rec.reasoning || "Recommendation generated from live signals.",
    action: mapRecommendationAction(rec.action_type),
    status: RecommendationStatus.New,
    priority: mapRecommendationPriority(rec.urgency_score),
    confidence: mapRecommendationConfidence(rec.confidence),
    confidenceLabel: recommendationConfidenceLabel(rec.confidence),
    expectedLift: Math.min(Math.max((rec.urgency_score ?? 0) / 100, 0), 1),
    product: rec.product_title,
    competitor: null,
    createdAt: rec.created_at,
  }))
}

export async function getCompetitors(
  signal?: AbortSignal
): Promise<Competitor[]> {
  const { data } = await apiClient.get<PaginatedResponse<ApiCompetitorRecord>>(
    "/dashboard/competitors",
    { signal }
  )
  return data.items.map((competitor) => {
    const competitorPrice = toNumber(competitor.competitor_price)
    const sellerPrice = toNumber(competitor.seller_price)
    return {
      id: competitor.competitor_id,
      product: competitor.product_title,
      competitor: competitor.competitor_title,
      competitorPrice,
      sellerPrice,
      priceGap: sellerPrice - competitorPrice,
      stockStatus: mapStockStatus(competitor.stock_status),
      urgencyScore: computeCompetitorUrgencyScore(
        competitor.price_gap_percent,
        competitor.stock_status
      ),
      recommendationAction: resolveRecommendationActionLabel(
        competitor.seller_price,
        competitor.competitor_price
      ),
      trend: mapCompetitorTrend(competitor.price_trend),
      lastUpdated: competitor.created_at,
      status: mapCompetitorStatus(),
    }
  })
}

type ApiCompetitorPricePoint = {
  timestamp: string
  competitor_price: number
  seller_price: number
  market_average: number
}

export async function getCompetitorPriceTrend(
  signal?: AbortSignal
): Promise<CompetitorPricePoint[]> {
  const { data } = await apiClient.get<ApiCompetitorPricePoint[]>(
    "/dashboard/competitor-price-trend",
    { signal }
  )
  return data.map((point) => ({
    timestamp: point.timestamp,
    competitorPrice: point.competitor_price,
    sellerPrice: point.seller_price,
    marketAverage: point.market_average,
  }))
}
