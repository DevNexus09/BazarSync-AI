import { describe, expect, it } from "vitest"

import {
  calculateImpactPercentage,
  calculateRevenueSimulation,
  recommendBestPrice,
  type RevenueSimulation,
} from "./revenueSimulator"

describe("revenue simulator", () => {
  it("calculates simulations, baseline, recommendation, and impacts", () => {
    const result = calculateRevenueSimulation({
      candidatePrices: [319, 299, 309],
      unitCost: 180,
      baselinePrice: 309,
      baselineMonthlyUnits: 100,
    })

    expect(result.simulations.map((item) => item.price)).toEqual([
      299,
      309,
      319,
    ])
    expect(result.baseline).toEqual({
      price: 309,
      estimatedUnits: 100,
      revenue: 30900,
      profit: 12900,
      margin: 41.75,
    })
    expect(result.recommendedSimulation.price).toBe(result.recommendedPrice)
    expect(result.expectedRevenueImpact).toMatch(/^[+-]\d+\.\d{2}%$/)
    expect(result.expectedProfitImpact).toMatch(/^[+-]\d+\.\d{2}%$/)
  })

  it("deduplicates candidate prices and marks prices below unit cost", () => {
    const result = calculateRevenueSimulation({
      candidatePrices: [99, 99, 120],
      unitCost: 100,
      baselinePrice: 120,
      baselineMonthlyUnits: 50,
      priceElasticity: -1,
    })

    expect(result.simulations).toHaveLength(2)
    expect(result.simulations[0]).toMatchObject({
      price: 99,
      warning: "Price is below unit cost",
    })
  })

  it("rejects invalid input clearly", () => {
    expect(() =>
      calculateRevenueSimulation({
        candidatePrices: [299],
        unitCost: 100,
        baselinePrice: 299,
        baselineMonthlyUnits: 50,
        priceElasticity: 1,
      })
    ).toThrow("priceElasticity must be zero or negative")

    expect(() =>
      calculateRevenueSimulation({
        candidatePrices: [],
        unitCost: 100,
        baselinePrice: 299,
        baselineMonthlyUnits: 50,
      })
    ).toThrow("candidatePrices must be a non-empty array.")
  })

  it("prefers higher margin when profits are very similar", () => {
    const simulations: RevenueSimulation[] = [
      simulation({ price: 100, profit: 1000, margin: 20 }),
      simulation({ price: 110, profit: 1002, margin: 25 }),
    ]

    expect(recommendBestPrice(simulations).price).toBe(110)
  })

  it("prefers the lower price when profit and margin are tied", () => {
    const simulations: RevenueSimulation[] = [
      simulation({ price: 110, profit: 1000, margin: 20 }),
      simulation({ price: 100, profit: 1000, margin: 20 }),
    ]

    expect(recommendBestPrice(simulations).price).toBe(100)
  })

  it("formats impact percentages with explicit signs", () => {
    expect(calculateImpactPercentage(108.25, 100)).toBe("+8.25%")
    expect(calculateImpactPercentage(91.75, 100)).toBe("-8.25%")
    expect(calculateImpactPercentage(0, 0)).toBe("+0.00%")
  })
})

function simulation(
  overrides: Pick<RevenueSimulation, "price" | "profit" | "margin">
): RevenueSimulation {
  return {
    estimatedUnits: 10,
    revenue: 1000,
    ...overrides,
  }
}
