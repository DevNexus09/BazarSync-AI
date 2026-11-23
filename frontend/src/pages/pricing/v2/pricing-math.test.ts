import { describe, expect, it } from "vitest"

import type { PricingPolicy } from "@/services/pricing-v2-service"

import { elasticityLabel, fromPaisa, positionLabel, sliderBounds, toPaisa } from "./pricing-math"

const policy = (overrides: Partial<PricingPolicy> = {}): PricingPolicy => ({
  isDefault: false,
  minimumMarginRate: "0.15",
  minimumUnitProfit: "0.00",
  maximumPriceDecreaseRate: "0.10",
  maximumPriceIncreaseRate: "0.10",
  minimumAllowedPrice: null,
  maximumAllowedPrice: null,
  priceIncrement: "5.00",
  ...overrides,
})

describe("paisa conversion", () => {
  it("round-trips decimal strings exactly", () => {
    expect(toPaisa("349.50")).toBe(34950)
    expect(toPaisa("0.1")).toBe(10)
    expect(toPaisa("12")).toBe(1200)
    expect(fromPaisa(34950)).toBe("349.50")
    expect(fromPaisa(toPaisa("0.10") + toPaisa("0.20"))).toBe("0.30")
  })

  it("rejects non-money input", () => {
    expect(() => toPaisa("abc")).toThrow()
  })
})

describe("sliderBounds", () => {
  it("snaps to the price step within the policy change limits", () => {
    expect(sliderBounds("349.00", policy())).toEqual({ min: 31500, max: 38000, step: 500, value: 35000 })
  })

  it("respects absolute minimum and maximum prices", () => {
    const bounds = sliderBounds("349.00", policy({ minimumAllowedPrice: "330.00", maximumAllowedPrice: "360.00" }))
    expect([bounds.min, bounds.max]).toEqual([33000, 36000])
  })

  it("falls back to ±30% and a 1 taka step without a policy", () => {
    expect(sliderBounds("100.00", undefined)).toEqual({ min: 7000, max: 13000, step: 100, value: 10000 })
  })

  it("never inverts when limits collapse the range", () => {
    const bounds = sliderBounds("100.00", policy({ maximumAllowedPrice: "50.00" }))
    expect(bounds.max).toBeGreaterThanOrEqual(bounds.min)
    expect(bounds.value).toBe(bounds.min)
  })
})

describe("labels", () => {
  it("names the elasticity source", () => {
    expect(elasticityLabel("HISTORICAL_ELASTICITY", "-0.9")).toBe("Using your sales history (elasticity −0.9)")
    expect(elasticityLabel("CONSERVATIVE_HEURISTIC", "-1.2")).toContain("Estimated")
    expect(elasticityLabel("INSUFFICIENT_DATA", null)).toBe("Not enough sales data to estimate demand")
    expect(elasticityLabel("POOLED_CATEGORY", "-1.64")).toBe("Using sales of similar products in your category (elasticity −1.6)")
  })

  it("describes market position", () => {
    expect(positionLabel("ABOVE_MARKET", "0.0906")).toBe("9% above market")
    expect(positionLabel("BELOW_MARKET", "-0.0769")).toBe("8% below market")
    expect(positionLabel("NO_MARKET_DATA", null)).toBe("No market data")
  })
})
