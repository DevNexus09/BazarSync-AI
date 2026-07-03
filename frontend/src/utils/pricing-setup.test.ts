import { describe, expect, it } from "vitest"

import type { RevenueSimulationResponse } from "@/types/pricing-simulator"

import {
  buildMarketplaceFeeSetupPath,
  isMissingFeeDataReason,
  percentToRate,
  simulationNeedsFeeSetup,
} from "./pricing-setup"

const baseSimulation: RevenueSimulationResponse = {
  sellerId: "seller-1",
  productId: "product-1",
  productTitle: "Rice 5kg",
  pricingAnalyticsId: "analytics-1",
  currentPrice: 299,
  baselineUnits: null,
  baselineExpectedRevenue: null,
  baselineExpectedProfit: null,
  forecastHorizonDays: 30,
  demandMethod: "CONSERVATIVE_HEURISTIC",
  dataStatus: "LIMITED",
  confidenceScore: 35,
  calculatedAt: "2026-07-02T00:00:00Z",
  scenarios: [],
  evidence: {},
}

describe("pricing setup helpers", () => {
  it("detects missing fee data across backend and display formats", () => {
    expect(isMissingFeeDataReason("MISSING_FEE_DATA")).toBe(true)
    expect(isMissingFeeDataReason("MISSING FEE DATA")).toBe(true)
    expect(isMissingFeeDataReason("Missing fee data")).toBe(true)
    expect(isMissingFeeDataReason("BELOW_MINIMUM_SAFE_PRICE")).toBe(false)
  })

  it("flags simulations where most candidates are blocked by missing fees", () => {
    expect(
      simulationNeedsFeeSetup({
        ...baseSimulation,
        scenarios: [
          blockedScenario("MISSING_FEE_DATA"),
          blockedScenario("Missing fee data"),
          blockedScenario("BELOW_MINIMUM_SAFE_PRICE"),
        ],
      })
    ).toBe(true)
  })

  it("builds setup route with product query params", () => {
    expect(
      buildMarketplaceFeeSetupPath({
        productId: "product-1",
        marketplace: "Daraz Bangladesh",
        category: "Grocery",
        currency: "BDT",
      })
    ).toBe(
      "/app/pricing/fee-setup?productId=product-1&marketplace=Daraz+Bangladesh&category=Grocery&currency=BDT"
    )
  })

  it("converts seller percentage input to decimal rates", () => {
    expect(percentToRate(8)).toBe(0.08)
    expect(percentToRate(2.5)).toBe(0.025)
  })
})

function blockedScenario(reason: string) {
  return {
    candidatePrice: 299,
    action: "HOLD" as const,
    isAllowed: false,
    rejectionReasons: [reason],
    expectedUnitsLower: null,
    expectedUnits: null,
    expectedUnitsUpper: null,
    expectedRevenue: null,
    expectedProfit: null,
    revenueImpact: null,
    profitImpact: null,
    unitProfit: null,
    marginRate: null,
    minimumSafePrice: null,
    confidenceScore: 0,
    estimationMethod: "CONSERVATIVE_HEURISTIC" as const,
    dataStatus: "LIMITED" as const,
    evidence: {},
  }
}
