import { beforeEach, describe, expect, it, vi } from "vitest"

import apiClient from "@/api/client"

import { createMarketplaceFeePolicy } from "./pricing-policy-service"

vi.mock("@/api/client", () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
  },
}))

describe("pricing policy service", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("posts marketplace fee policies to the backend endpoint", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        id: "fee-1",
        seller_id: "seller-1",
        product_id: "product-1",
        marketplace: "Daraz Bangladesh",
        category: "Grocery",
        currency: "BDT",
        percentage_commission_rate: "0.08",
        payment_fee_rate: "0.025",
        fixed_per_order_fee: "5.00",
        fixed_per_unit_fee: "1.00",
        fulfilment_fee: "2.00",
        shipping_subsidy: "3.00",
        other_variable_cost: "4.00",
        effective_from: "2026-07-02T00:00:00Z",
        is_default: false,
      },
    })

    await createMarketplaceFeePolicy({
      productId: "product-1",
      marketplace: "Daraz Bangladesh",
      category: "Grocery",
      currency: "BDT",
      percentageCommissionRate: 0.08,
      paymentFeeRate: 0.025,
      fixedPerOrderFee: 5,
      fixedPerUnitFee: 1,
      fulfilmentFee: 2,
      shippingSubsidy: 3,
      otherVariableCost: 4,
      effectiveFrom: "2026-07-02T00:00:00.000Z",
    })

    expect(apiClient.post).toHaveBeenCalledWith(
      "/pricing-policies/marketplace-fees",
      expect.objectContaining({
        product_id: "product-1",
        percentage_commission_rate: 0.08,
        payment_fee_rate: 0.025,
        source: "manual",
        version: "v1",
        is_active: true,
      })
    )
  })
})
