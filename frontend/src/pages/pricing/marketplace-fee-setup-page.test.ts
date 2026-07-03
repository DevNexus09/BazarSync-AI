import { describe, expect, it } from "vitest"

import {
  buildMarketplaceFeePayload,
  type FeeFormState,
} from "@/utils/marketplace-fee-setup"

const baseForm: FeeFormState = {
  productId: "product-1",
  marketplace: "Daraz Bangladesh",
  category: "Grocery",
  currency: "BDT",
  commissionRatePercent: "8",
  paymentFeeRatePercent: "2.5",
  fixedPerOrderFee: "5",
  fixedPerUnitFee: "1",
  fulfilmentFee: "2",
  shippingSubsidy: "3",
  otherVariableCost: "4",
  effectiveFrom: "2026-07-02",
}

describe("marketplace fee setup form helpers", () => {
  it("validates required fields", () => {
    expect(buildMarketplaceFeePayload({ ...baseForm, marketplace: "" })).toEqual({
      error: "Marketplace is required.",
    })
  })

  it("converts percentage inputs before submission", () => {
    const result = buildMarketplaceFeePayload(baseForm)

    expect("value" in result ? result.value.percentageCommissionRate : null).toBe(0.08)
    expect("value" in result ? result.value.paymentFeeRate : null).toBe(0.025)
  })
})
