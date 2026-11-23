export type DemandEstimationMethod =
  | "HISTORICAL_ELASTICITY"
  | "CATEGORY_PRIOR"
  | "CONSERVATIVE_HEURISTIC"
  | "POOLED_CATEGORY"
  | "INSUFFICIENT_DATA"

export type DemandDataStatus = "SUFFICIENT" | "LIMITED" | "INSUFFICIENT"

export type PricingSimulatorAction =
  | "PRICE_LOWER"
  | "PRICE_RAISE"
  | "HOLD"

export type RevenueSimulationRequest = {
  candidatePrices: number[]
  forecastHorizonDays: number
}

export type RevenueSimulationScenario = {
  candidatePrice: number
  action: PricingSimulatorAction
  isAllowed: boolean
  rejectionReasons: string[]
  expectedUnitsLower: number | null
  expectedUnits: number | null
  expectedUnitsUpper: number | null
  expectedRevenue: number | null
  expectedProfit: number | null
  revenueImpact: number | null
  profitImpact: number | null
  unitProfit: number | null
  marginRate: number | null
  minimumSafePrice: number | null
  confidenceScore: number
  estimationMethod: DemandEstimationMethod
  dataStatus: DemandDataStatus
  evidence: Record<string, unknown>
}

export type RevenueSimulationResponse = {
  sellerId: string
  productId: string
  productTitle: string
  pricingAnalyticsId: string
  currentPrice: number
  baselineUnits: number | null
  baselineExpectedRevenue: number | null
  baselineExpectedProfit: number | null
  forecastHorizonDays: number
  demandMethod: DemandEstimationMethod
  dataStatus: DemandDataStatus
  confidenceScore: number
  calculatedAt: string
  scenarios: RevenueSimulationScenario[]
  evidence: Record<string, unknown>
}

export type RevenueSimulationExplanationResponse = {
  simulation: RevenueSimulationResponse
  explanation: string
  summary: string
  risks: string[]
  nextSteps: string[]
  model: string | null
}
