import type { DashboardEvidence } from "./dashboardEvidence"

export type RecommendationAction = "LOWER" | "RAISE" | "HOLD" | "REORDER"
export type RecommendationConfidence = "LOW" | "MEDIUM" | "HIGH"

export type RecommendationAnalytics = {
  competitorMedianPrice: number | null
  priceGapPercent: number | null
  stockRiskScore: number | null
  stockRiskAvailable?: boolean | null
  stockCoverageAvailable?: boolean | null
  pricingPressureScore: number | null
  estimatedDaysOfStockLeft: number | null
  competitorsOos?: number | null
}

export type RecommendationResponse = {
  action: RecommendationAction
  confidence: RecommendationConfidence
  reasoningBn: string
  revenueOpportunity: number | null
}

export type RecommendationData = {
  success: boolean
  productId: string
  recommendation: RecommendationResponse
  analytics: RecommendationAnalytics
  createdAt: string
  evidence?: DashboardEvidence
}

export type RecommendationApiResponse = {
  success: boolean
  product_id: string
  recommendation: {
    action: RecommendationAction
    confidence: RecommendationConfidence
    reasoning_bn: string
    revenue_opportunity: number | string | null
  }
  analytics: {
    competitor_median_price: number | string | null
    price_gap_percent: number | string | null
    stock_risk_score: number | string | null
    stock_risk_available?: boolean | null
    stock_coverage_available?: boolean | null
    pricing_pressure_score: number | string | null
    estimated_days_of_stock_left: number | string | null
    competitors_oos?: number | string | null
  }
  created_at: string
  dashboard_evidence?: unknown
}

export type RecommendationQueuedResponse = {
  success: true
  status: "processing"
  product_id: string
  task_id: string
  job_id?: string
}

export type RecommendationGenerateApiResponse =
  | RecommendationApiResponse
  | RecommendationQueuedResponse

export type RecommendationQueuedResult = {
  queued: true
  taskId: string
  jobId?: string
  productId: string
}

export type RecommendationGenerateResult =
  | RecommendationData
  | RecommendationQueuedResult

export type RecommendationErrorResponse = {
  success: false
  detail: string
  error_code?: string | null
}

export type RecommendationJob = {
  jobId: string
  productId: string
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED"
  errorMessage: string | null
  result: RecommendationData | null
}
