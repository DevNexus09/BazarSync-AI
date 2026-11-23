import { describe, expect, it } from "vitest"

import type { DeadStockProduct } from "@/types/dead-stock"
import type { InventoryIntelligenceItem } from "@/types/inventory-intelligence"

import { buildTodoList, dataHealth, inventoryKpis, matchesUrgency, runsOutText, runwayScale, toCsv } from "./inventory-logic"

const TODAY = new Date("2026-11-23T08:00:00Z")

export function item(overrides: Partial<InventoryIntelligenceItem>): InventoryIntelligenceItem {
  return {
    productId: overrides.productName ?? "p",
    productName: "Product",
    category: null,
    riskLevel: "MEDIUM",
    riskScore: 50,
    dataStatus: "SUFFICIENT",
    daysRemaining: 30,
    predictedStockoutDate: null,
    reorderAction: "HOLD",
    recommendationStatus: "OPEN",
    recommendedQuantity: 0,
    reorderDeadline: null,
    calculationVersion: "v1",
    asOfDate: "2026-11-23",
    lastUpdatedAt: null,
    reorderRecommendationId: "r",
    supplierLeadTimeDays: 7,
    supplierLeadTimeDefaulted: false,
    ...overrides,
  }
}

function dead(overrides: Partial<DeadStockProduct>): DeadStockProduct {
  return {
    productId: overrides.productName ?? "d",
    productName: "Dead",
    category: null,
    currentStock: 10,
    eligibleUnsoldQuantity: 10,
    inventoryAgeDays: 120,
    inventoryAgeIsEstimated: false,
    ageSource: null,
    daysSinceLastSale: 74,
    classification: "DEAD_STOCK",
    riskScore: 80,
    riskLevel: "HIGH",
    lockedCapital: 1000,
    lockedCapitalCurrency: "BDT",
    primaryRecommendation: "DISCOUNT",
    recommendationStatus: null,
    potentialRecovery: null,
    potentialRecoveryLow: null,
    potentialRecoveryHigh: null,
    dataStatus: "SUFFICIENT",
    lastCalculatedAt: null,
    ...overrides,
  }
}

describe("buildTodoList", () => {
  const items = [
    item({ productName: "Sugar", reorderAction: "REORDER", recommendedQuantity: 120, reorderDeadline: "2026-11-26", daysRemaining: 9 }),
    item({ productName: "Flour", daysRemaining: 40 }),
    item({ productName: "Oil", reorderAction: "REORDER", recommendedQuantity: 150, reorderDeadline: "2026-11-23", daysRemaining: 3, supplierLeadTimeDays: 8 }),
    item({ productName: "Rice", daysRemaining: 0, reorderAction: "REORDER", recommendedQuantity: 60 }),
    item({ productName: "Salt", reorderAction: "REORDER", reorderDeadline: "2026-11-30", daysRemaining: 12 }),
    item({ productName: "Tea", daysRemaining: 0, recommendationStatus: "ORDERED" }),
  ]
  const deadStock = [dead({ productName: "Soap", lockedCapital: 500 }), dead({ productName: "Comb", lockedCapital: 9000 }), dead({ productName: "Slow", classification: "SLOW_MOVING" })]

  it("ranks out of stock, then before lead time, then deadlines, then cash stuck", () => {
    const todo = buildTodoList(items, deadStock, TODAY)
    expect(todo.map((t) => `${t.priority}:${t.productId}`)).toEqual([
      "out_of_stock:Rice",
      "before_lead_time:Oil",
      "deadline_soon:Sugar",
      "dead_stock:Comb",
      "dead_stock:Soap",
    ])
    expect(todo[0].text).toBe("Rice is out of stock — order 60")
    expect(todo[1].text).toBe("Reorder Oil — runs out in 3 days, lead time 8 days")
    expect(todo[2].text).toBe("Reorder Sugar — order 120 by 26 Nov")
    expect(todo[3].text).toBe("Comb: no sale in 74 days — try a discount")
  })

  it("skips items already ordered or dismissed and caps the list", () => {
    expect(buildTodoList(items, deadStock, TODAY).some((t) => t.productId === "Tea")).toBe(false)
    expect(buildTodoList(items, deadStock, TODAY, 2)).toHaveLength(2)
  })

  it("lists each product once, at its most urgent reason", () => {
    const todo = buildTodoList([item({ productName: "Oil", daysRemaining: 0, reorderAction: "REORDER", reorderDeadline: "2026-11-23" })], [], TODAY)
    expect(todo.map((t) => t.priority)).toEqual(["out_of_stock"])
  })
})

describe("inventory figures", () => {
  it("counts KPIs and data health", () => {
    const rows = [
      item({ productName: "a", daysRemaining: 0 }),
      item({ productName: "b", daysRemaining: 3, reorderAction: "REORDER" }),
      item({ productName: "c", daysRemaining: 20, reorderAction: "REORDER", recommendationStatus: "ORDERED", supplierLeadTimeDefaulted: true }),
      item({ productName: "d", daysRemaining: null, dataStatus: "INSUFFICIENT" }),
    ]
    expect(inventoryKpis(rows)).toEqual({ outOfStock: 1, runsOutWithinWeek: 1, reorderNow: 1 })
    const health = dataHealth(rows)
    expect(health.defaultedLeadTime.map((r) => r.productId)).toEqual(["c"])
    expect(health.insufficientData.map((r) => r.productId)).toEqual(["d"])
  })

  it("writes runway in plain language", () => {
    expect(runsOutText({ daysRemaining: 6, predictedStockoutDate: "2026-11-29" })).toBe("Runs out in 6 days (29 Nov)")
    expect(runsOutText({ daysRemaining: 0.4, predictedStockoutDate: null })).toBe("Runs out in 1 day")
    expect(runsOutText({ daysRemaining: 0, predictedStockoutDate: null })).toBe("Out of stock")
    expect(runsOutText({ daysRemaining: null, predictedStockoutDate: null })).toBeNull()
  })

  it("scales the runway bar against lead time", () => {
    expect(runwayScale(3, 8)).toEqual({ fill: 30, leadMarker: 80, beforeLeadTime: true })
    expect(runwayScale(40, 8)?.beforeLeadTime).toBe(false)
    expect(runwayScale(null, 8)).toBeNull()
    expect(runwayScale(5, null)?.leadMarker).toBeNull()
  })
})

describe("reorder export and filters", () => {
  it("escapes CSV values and leaves order quantity empty when no reorder", () => {
    const csv = toCsv([
      item({ productName: 'Rice "Premium", 5kg', reorderAction: "REORDER", recommendedQuantity: 60, reorderDeadline: "2026-11-25" }),
      item({ productName: "Flour", recommendedQuantity: 0 }),
    ]).split("\n")
    expect(csv[0]).toBe("Product,Category,Days of stock left,Lead time (days),Order quantity,Order by,Status")
    expect(csv[1]).toBe('"Rice ""Premium"", 5kg",,30,7,60,2026-11-25,OPEN')
    expect(csv[2]).toBe("Flour,,30,7,,,OPEN")
  })

  it("filters by urgency", () => {
    expect(matchesUrgency(item({ daysRemaining: 0 }), "out")).toBe(true)
    expect(matchesUrgency(item({ daysRemaining: 5 }), "week")).toBe(true)
    expect(matchesUrgency(item({ reorderAction: "REORDER", recommendationStatus: "ORDERED" }), "reorder")).toBe(false)
    expect(matchesUrgency(item({ reorderAction: "HOLD" }), "ok")).toBe(true)
  })
})
