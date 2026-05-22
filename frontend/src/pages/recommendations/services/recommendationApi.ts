import axios from "axios"

import apiClient from "@/api/client"

import type {
  RecommendationApiResponse,
  RecommendationData,
} from "../types/recommendation"

const toNumber = (value: number | string | null | undefined) => {
  if (value === null || value === undefined) {
    return null
  }
  const parsed = typeof value === "number" ? value : Number(value)
  return Number.isNaN(parsed) ? null : parsed
}

const mapRecommendation = (
  data: RecommendationApiResponse
): RecommendationData => ({
  success: data.success,
  productId: String(data.product_id),
  recommendation: {
    action: data.recommendation.action,
    confidence: data.recommendation.confidence,
    reasoningBn: data.recommendation.reasoning_bn,
    revenueOpportunity: Number(data.recommendation.revenue_opportunity ?? 0),
  },
  analytics: {
    competitorMedianPrice: toNumber(data.analytics.competitor_median_price),
    priceGapPercent: toNumber(data.analytics.price_gap_percent),
    stockRiskScore: Number(data.analytics.stock_risk_score ?? 0),
    pricingPressureScore: Number(data.analytics.pricing_pressure_score ?? 0),
    estimatedDaysOfStockLeft: Number(
      data.analytics.estimated_days_of_stock_left ?? 0
    ),
    competitorsOos: toNumber(data.analytics.competitors_oos),
  },
  createdAt: data.created_at,
})

export async function generateRecommendation(
  productId: string
): Promise<RecommendationData> {
  if (!productId) {
    throw new Error("Product id is required to generate a recommendation.")
  }

  const { data } = await apiClient.post<RecommendationApiResponse>(
    `/recommendations/generate/${encodeURIComponent(productId)}`
  )

  return mapRecommendation(data)
}

export async function getLatestRecommendation(
  productId: string
): Promise<RecommendationData | null> {
  if (!productId) {
    throw new Error("Product id is required to fetch recommendations.")
  }

  try {
    const { data } = await apiClient.get<RecommendationApiResponse>(
      `/recommendations/latest/${encodeURIComponent(productId)}`
    )
    return mapRecommendation(data)
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return null
    }
    throw error
  }
}
