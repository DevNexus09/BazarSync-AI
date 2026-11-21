import { AxiosError } from "axios"
import { afterEach, describe, expect, it, vi } from "vitest"

import apiClient from "@/api/client"

import { getLatestRecommendation, getRecommendationJob } from "./recommendationApi"

afterEach(() => vi.restoreAllMocks())

describe("recommendation API compatibility", () => {
  it("preserves observed zero and maps blank, missing and nonfinite metrics to unavailable", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: {
      success: true, product_id: "a", created_at: "2026-11-17T11:00:00Z",
      recommendation: { action: "HOLD", confidence: "LOW", reasoning_bn: "বর্তমান দাম রাখুন", revenue_opportunity: null },
      analytics: {
        competitor_median_price: " ",
        price_gap_percent: "Infinity",
        stock_risk_score: null,
        pricing_pressure_score: "NaN",
        estimated_days_of_stock_left: undefined,
        competitors_oos: "0",
      },
    } })
    const result = await getLatestRecommendation("a")
    expect(result?.recommendation.revenueOpportunity).toBeNull()
    expect(result?.analytics).toMatchObject({
      competitorMedianPrice: null,
      priceGapPercent: null,
      stockRiskScore: null,
      pricingPressureScore: null,
      estimatedDaysOfStockLeft: null,
      competitorsOos: 0,
    })
  })

  it("preserves backend precision for exact candidate prices", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: {
      success: true, product_id: "a", created_at: "2026-11-17T11:00:00Z",
      recommendation: { action: "LOWER", confidence: "MEDIUM", reasoning_bn: "দাম কমানোর পরামর্শ", revenue_opportunity: 0 },
      analytics: {},
      dashboard_evidence: { target_price: "400.25", pricing_candidates: [
        { price: "400.25", constraints_passed: true },
      ] },
    } })
    expect((await getLatestRecommendation("a"))?.evidence?.target_price).toBe(400.25)
  })

  it("propagates session expiration from both recommendation endpoints", async () => {
    const error = Object.assign(new AxiosError("Expired"), { response: { status: 401 } })
    vi.spyOn(apiClient, "get").mockRejectedValue(error)
    await expect(getLatestRecommendation("a")).rejects.toBe(error)
    await expect(getRecommendationJob("a", "job")).rejects.toBe(error)
  })
})
