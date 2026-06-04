export type RecommendationAction = "LOWER" | "RAISE" | "HOLD" | "REORDER"
export type RecommendationConfidence = "LOW" | "MEDIUM" | "HIGH"

export type RecommendationAnalytics = {
  competitorMedianPrice: number | null
  priceGapPercent: number | null
  stockRiskScore: number
  pricingPressureScore: number
  estimatedDaysOfStockLeft: number
  competitorsOos?: number | null
}

export type RecommendationResponse = {
  action: RecommendationAction
  confidence: RecommendationConfidence
  reasoningBn: string
  revenueOpportunity: number
}

export type RecommendationData = {
  success: boolean
  productId: string
  recommendation: RecommendationResponse
  analytics: RecommendationAnalytics
  createdAt: string
}

export type RecommendationApiResponse = {
  success: boolean
  product_id: string
  recommendation: {
    action: RecommendationAction
    confidence: RecommendationConfidence
    reasoning_bn: string
    revenue_opportunity: number | string
  }
  analytics: {
    competitor_median_price: number | string | null
    price_gap_percent: number | string | null
    stock_risk_score: number | string
    pricing_pressure_score: number | string
    estimated_days_of_stock_left: number | string
    competitors_oos?: number | string | null
  }
  created_at: string
}

export type RecommendationQueuedResponse = {
  success: true
  status: "processing"
  product_id: string
  task_id: string
}

export type RecommendationGenerateApiResponse =
  | RecommendationApiResponse
  | RecommendationQueuedResponse

export type RecommendationQueuedResult = {
  queued: true
  taskId: string
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
