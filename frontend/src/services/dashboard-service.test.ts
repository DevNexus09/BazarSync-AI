import { beforeEach, describe, expect, it, vi } from "vitest"

import apiClient from "@/api/client"

import {
  getActivityFeed,
  getCompetitorPriceTrend,
  getMarketTrends,
  getOpportunityMetrics,
  mapOpportunityMetric,
} from "./dashboard-service"

vi.mock("@/api/client", () => ({
  default: { get: vi.fn() },
}))

describe("dashboard service", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("maps market trends from the backend", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: [
        {
          timestamp: "2026-11-20T00:00:00Z",
          demand_index: 40,
          urgency_index: 55,
          opportunity_index: 70,
          price_index: -5,
        },
      ],
    })

    await expect(getMarketTrends()).resolves.toEqual([
      {
        timestamp: "2026-11-20T00:00:00Z",
        demandIndex: 40,
        urgencyIndex: 55,
        opportunityIndex: 70,
        priceIndex: -5,
      },
    ])
    expect(apiClient.get).toHaveBeenCalledWith("/dashboard/market-trends", {
      signal: undefined,
    })
  })

  it("maps competitor price trend points", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: [
        {
          timestamp: "2026-11-20T00:00:00Z",
          competitor_price: 950,
          seller_price: 1000,
          market_average: 975,
        },
      ],
    })

    await expect(getCompetitorPriceTrend()).resolves.toEqual([
      {
        timestamp: "2026-11-20T00:00:00Z",
        competitorPrice: 950,
        sellerPrice: 1000,
        marketAverage: 975,
      },
    ])
  })

  it("passes the activity feed through and fetches metrics", async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ data: [] })
      .mockResolvedValueOnce({ data: [] })

    await expect(getActivityFeed()).resolves.toEqual([])
    await expect(getOpportunityMetrics()).resolves.toEqual([])
    expect(apiClient.get).toHaveBeenCalledWith("/dashboard/activity", {
      signal: undefined,
    })
    expect(apiClient.get).toHaveBeenCalledWith("/dashboard/opportunity-metrics", {
      signal: undefined,
    })
  })

  it("formats opportunity metrics and marks missing history", () => {
    expect(
      mapOpportunityMetric({
        id: "confidence",
        label: "Confidence",
        value: 90,
        delta: -20,
        trend: "down",
      })
    ).toEqual({
      id: "confidence",
      label: "Confidence",
      value: "90.0%",
      delta: "-20.0%",
      trend: "down",
    })

    expect(
      mapOpportunityMetric({
        id: "action-recommendation",
        label: "Action recommendation",
        value: "Raise price",
        delta: null,
        trend: "sideways",
      })
    ).toMatchObject({
      value: "Raise price",
      delta: "No prior signal",
      trend: "flat",
    })
  })
})
