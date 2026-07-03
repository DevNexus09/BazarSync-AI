export type RevenueSimulatorInput = {
  productId?: string
  productName?: string
  candidatePrices: number[]
  unitCost: number
  baselinePrice: number
  baselineMonthlyUnits: number
  priceElasticity?: number
}

export type RevenueSimulation = {
  price: number
  estimatedUnits: number
  revenue: number
  profit: number
  margin: number
  warning?: string
}

export type RevenueSimulationResult = {
  simulations: RevenueSimulation[]
  recommendedPrice: number
  recommendedSimulation: RevenueSimulation
  baseline: {
    price: number
    estimatedUnits: number
    revenue: number
    profit: number
    margin: number
  }
  expectedRevenueImpact: string
  expectedProfitImpact: string
}

const DEFAULT_PRICE_ELASTICITY = -1.2
const SIMILAR_PROFIT_TOLERANCE_RATE = 0.005
const BELOW_UNIT_COST_WARNING = "Price is below unit cost"

export function calculateRevenueSimulation(
  input: RevenueSimulatorInput
): RevenueSimulationResult {
  const validInput = validateInput(input)
  const priceElasticity = validInput.priceElasticity ?? DEFAULT_PRICE_ELASTICITY
  const candidatePrices = normalizeCandidatePrices(validInput.candidatePrices)

  const simulations = candidatePrices.map((candidatePrice) => {
    const estimatedUnits = Math.round(
      validInput.baselineMonthlyUnits *
        Math.pow(candidatePrice / validInput.baselinePrice, priceElasticity)
    )
    const revenue = roundToTwo(candidatePrice * estimatedUnits)
    const profit = roundToTwo((candidatePrice - validInput.unitCost) * estimatedUnits)
    const margin = roundToTwo(revenue > 0 ? (profit / revenue) * 100 : 0)

    return {
      price: candidatePrice,
      estimatedUnits,
      revenue,
      profit,
      margin,
      warning:
        candidatePrice < validInput.unitCost ? BELOW_UNIT_COST_WARNING : undefined,
    }
  })

  const baselineRevenue = roundToTwo(
    validInput.baselinePrice * validInput.baselineMonthlyUnits
  )
  const baselineProfit = roundToTwo(
    (validInput.baselinePrice - validInput.unitCost) *
      validInput.baselineMonthlyUnits
  )
  const baselineMargin = roundToTwo(
    baselineRevenue > 0 ? (baselineProfit / baselineRevenue) * 100 : 0
  )
  const recommendedSimulation = recommendBestPrice(simulations)

  return {
    simulations,
    recommendedPrice: recommendedSimulation.price,
    recommendedSimulation,
    baseline: {
      price: validInput.baselinePrice,
      estimatedUnits: validInput.baselineMonthlyUnits,
      revenue: baselineRevenue,
      profit: baselineProfit,
      margin: baselineMargin,
    },
    expectedRevenueImpact: calculateImpactPercentage(
      recommendedSimulation.revenue,
      baselineRevenue
    ),
    expectedProfitImpact: calculateImpactPercentage(
      recommendedSimulation.profit,
      baselineProfit
    ),
  }
}

export function recommendBestPrice(
  simulations: RevenueSimulation[]
): RevenueSimulation {
  if (!Array.isArray(simulations) || simulations.length === 0) {
    throw new Error("simulations must be a non-empty array.")
  }

  return [...simulations].sort(compareSimulations)[0]
}

export function calculateImpactPercentage(
  newValue: number,
  oldValue: number
): string {
  if (!Number.isFinite(newValue) || !Number.isFinite(oldValue)) {
    throw new Error("Impact values must be finite numbers.")
  }

  if (oldValue === 0) {
    if (newValue === 0) {
      return "+0.00%"
    }
    return newValue > 0 ? "+100.00%" : "-100.00%"
  }

  const impact = ((newValue - oldValue) / Math.abs(oldValue)) * 100
  return `${impact >= 0 ? "+" : ""}${roundToTwo(impact).toFixed(2)}%`
}

function validateInput(input: RevenueSimulatorInput): RevenueSimulatorInput {
  if (!input || typeof input !== "object") {
    throw new Error("Revenue simulation input is required.")
  }

  normalizeCandidatePrices(input.candidatePrices)

  if (!isFiniteNumber(input.unitCost) || input.unitCost < 0) {
    throw new Error("unitCost must be zero or positive.")
  }

  if (!isFiniteNumber(input.baselinePrice) || input.baselinePrice <= 0) {
    throw new Error("baselinePrice must be positive.")
  }

  if (
    !isFiniteNumber(input.baselineMonthlyUnits) ||
    input.baselineMonthlyUnits <= 0
  ) {
    throw new Error("baselineMonthlyUnits must be positive.")
  }

  if (
    input.priceElasticity !== undefined &&
    (!isFiniteNumber(input.priceElasticity) || input.priceElasticity > 0)
  ) {
    throw new Error(
      "priceElasticity must be zero or negative. Positive elasticity is not supported because price increases should not normally increase demand in this model."
    )
  }

  return input
}

function normalizeCandidatePrices(candidatePrices: number[]): number[] {
  if (!Array.isArray(candidatePrices) || candidatePrices.length === 0) {
    throw new Error("candidatePrices must be a non-empty array.")
  }

  if (candidatePrices.some((price) => !isFiniteNumber(price) || price <= 0)) {
    throw new Error("candidatePrices must contain positive numbers only.")
  }

  return [...new Set(candidatePrices.map(roundToTwo))].sort((a, b) => a - b)
}

function compareSimulations(
  first: RevenueSimulation,
  second: RevenueSimulation
): number {
  // Primary rule: choose the price with the highest expected profit.
  const profitDifference = second.profit - first.profit
  const tolerance =
    Math.max(Math.abs(first.profit), Math.abs(second.profit), 1) *
    SIMILAR_PROFIT_TOLERANCE_RATE
  if (Math.abs(profitDifference) > tolerance) {
    return profitDifference
  }

  // If profit is very close, prefer the healthier margin.
  if (second.margin !== first.margin) {
    return second.margin - first.margin
  }

  // Final tie-breaker: lower price reduces customer resistance.
  return first.price - second.price
}

function isFiniteNumber(value: number): boolean {
  return typeof value === "number" && Number.isFinite(value)
}

function roundToTwo(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100
}
