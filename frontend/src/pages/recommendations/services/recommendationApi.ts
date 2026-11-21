import axios from "axios"

import apiClient from "@/api/client"

import { dashboardEvidenceSchema } from "../types/dashboardEvidence"
import type {
  RecommendationApiResponse,
  RecommendationData,
  RecommendationGenerateApiResponse,
  RecommendationGenerateResult,
  RecommendationJob,
  RecommendationQueuedResponse,
} from "../types/recommendation"

const toNumber = (value: number | string | null | undefined) => {
  if (value === null || value === undefined || (typeof value === "string" && !value.trim())) {
    return null
  }
  const parsed = typeof value === "number" ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const mapRecommendation = (data: RecommendationApiResponse): RecommendationData => ({
  success: data.success,
  evidence: dashboardEvidenceSchema.safeParse(data.dashboard_evidence).data,
  productId: String(data.product_id),
  recommendation: {
    action: data.recommendation.action,
    confidence: data.recommendation.confidence,
    reasoningBn: data.recommendation.reasoning_bn,
    revenueOpportunity: toNumber(data.recommendation.revenue_opportunity),
  },
  analytics: {
    competitorMedianPrice: toNumber(data.analytics.competitor_median_price),
    priceGapPercent: toNumber(data.analytics.price_gap_percent),
    stockRiskScore: toNumber(data.analytics.stock_risk_score),
    stockRiskAvailable: data.analytics.stock_risk_available,
    stockCoverageAvailable: data.analytics.stock_coverage_available,
    pricingPressureScore: toNumber(data.analytics.pricing_pressure_score),
    estimatedDaysOfStockLeft: toNumber(
      data.analytics.estimated_days_of_stock_left
    ),
    competitorsOos: toNumber(data.analytics.competitors_oos),
  },
  createdAt: data.created_at,
})

const isQueuedResponse = (
  data: RecommendationGenerateApiResponse
): data is RecommendationQueuedResponse =>
  "status" in data && data.status === "processing"

export async function generateRecommendation(
  productId: string,
  requestKey?: string,
): Promise<RecommendationGenerateResult> {
  if (!productId) {
    throw new Error("Product id is required to generate a recommendation.")
  }

  const { data } = await apiClient.post<RecommendationGenerateApiResponse>(
    `/recommendations/generate/${encodeURIComponent(productId)}`,
    undefined,
    requestKey ? { headers: { "Idempotency-Key": requestKey } } : undefined,
  )

  if (isQueuedResponse(data)) {
    return {
      queued: true,
      taskId: data.task_id,
      jobId: data.job_id,
      productId: String(data.product_id),
    }
  }

  return mapRecommendation(data)
}

export async function getRecommendationJob(productId: string, jobId?: string): Promise<RecommendationJob | null> {
  try {
    const { data } = await apiClient.get<{
      job_id: string
      product_id: string
      status: RecommendationJob["status"]
      error_message: string | null
      result: RecommendationApiResponse | null
    }>(jobId
      ? `/recommendations/jobs/${encodeURIComponent(jobId)}`
      : `/recommendations/products/${encodeURIComponent(productId)}/job`)
    return {
      jobId: data.job_id,
      productId: data.product_id,
      status: data.status,
      errorMessage: data.error_message,
      result: data.result ? mapRecommendation(data.result) : null,
    }
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return null
    }
    throw error
  }
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
