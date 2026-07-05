import { beforeEach, describe, expect, it, vi } from "vitest"

import apiClient from "@/api/client"

import {
  createInventoryStockIn,
  createPricingPolicy,
  createVisibilityMetric,
  importSalesRecord,
  percentToRate,
} from "./phase9-setup-service"

vi.mock("@/api/client", () => ({
  default: {
    post: vi.fn(),
  },
}))

describe("phase9 setup service", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(apiClient.post).mockResolvedValue({ data: {} })
  })

  it("posts inventory stock-in payload", async () => {
    await createInventoryStockIn({
      productId: "product-1",
      quantity: 25,
      receivedAt: "2026-04-20T00:00:00.000Z",
      unitCost: 500,
      currency: "BDT",
      sourceReference: "manual-initial-stock",
      notes: "Initial stock",
    })

    expect(apiClient.post).toHaveBeenCalledWith(
      "/inventory/stock-in",
      expect.objectContaining({ product_id: "product-1", quantity: 25, unit_cost: 500 })
    )
  })

  it("posts sales import payload with completed status", async () => {
    await importSalesRecord({
      productId: "product-1",
      quantity: 2,
      soldAt: "2026-06-10T09:30:00.000Z",
      status: "COMPLETED",
      unitPrice: 950,
      currency: "BDT",
      sourceReference: "manual-sale-001",
      isTestOrder: false,
    })

    expect(apiClient.post).toHaveBeenCalledWith(
      "/sales/import",
      expect.objectContaining({
        records: [expect.objectContaining({ status: "COMPLETED", is_test_order: false })],
      })
    )
  })

  it("converts pricing percentages before posting policy", async () => {
    expect(percentToRate(15)).toBe(0.15)
    expect(percentToRate(20)).toBe(0.2)

    await createPricingPolicy({
      productId: "product-1",
      marketplace: "DARAZ",
      currency: "BDT",
      minimumMarginPercent: 15,
      minimumUnitProfit: 0,
      maximumDiscountPercent: 20,
      maximumPriceIncreasePercent: 10,
      minimumAllowedPrice: null,
      maximumAllowedPrice: null,
      priceIncrement: 1,
      objective: "MAXIMIZE_EXPECTED_PROFIT",
      effectiveFrom: "2026-07-05T00:00:00.000Z",
    })

    expect(apiClient.post).toHaveBeenCalledWith(
      "/pricing-policies",
      expect.objectContaining({
        minimum_margin_rate: 0.15,
        maximum_price_decrease_rate: 0.2,
        maximum_price_increase_rate: 0.1,
      })
    )
  })

  it("posts visibility metrics payload", async () => {
    await createVisibilityMetric({
      productId: "product-1",
      marketplace: "DARAZ",
      metricDate: "2026-07-05",
      impressions: 1200,
      views: 180,
      clicks: 36,
      searchRank: 18,
      listingQualityScore: 62,
      conversionRate: 0.02,
      source: "manual",
    })

    expect(apiClient.post).toHaveBeenCalledWith(
      "/products/product-1/visibility-metrics",
      expect.objectContaining({ impressions: 1200, listing_quality_score: 62 })
    )
  })
})
