import apiClient from "@/api/client"
import type {
  RevenueSimulationExplanationResponse,
  RevenueSimulationRequest,
  RevenueSimulationResponse,
  RevenueSimulationScenario,
} from "@/types/pricing-simulator"

type ScenarioApi = {
  candidate_price: string | number
  action: RevenueSimulationScenario["action"]
  is_allowed: boolean
  rejection_reasons: string[]
  expected_units_lower: string | number | null
  expected_units: string | number | null
  expected_units_upper: string | number | null
  expected_revenue: string | number | null
  expected_profit: string | number | null
  revenue_impact: string | number | null
  profit_impact: string | number | null
  unit_profit: string | number | null
  margin_rate: string | number | null
  minimum_safe_price: string | number | null
  confidence_score: string | number
  estimation_method: RevenueSimulationScenario["estimationMethod"]
  data_status: RevenueSimulationScenario["dataStatus"]
  evidence: Record<string, unknown>
}

type SimulationApi = {
  seller_id: string
  product_id: string
  product_title: string
  pricing_analytics_id: string
  current_price: string | number
  baseline_units: string | number | null
  baseline_expected_revenue: string | number | null
  baseline_expected_profit: string | number | null
  forecast_horizon_days: number
  demand_method: RevenueSimulationResponse["demandMethod"]
  data_status: RevenueSimulationResponse["dataStatus"]
  confidence_score: string | number
  calculated_at: string
  scenarios: ScenarioApi[]
  evidence: Record<string, unknown>
}

type ExplanationApi = {
  simulation: SimulationApi
  explanation: string
  summary: string
  risks: string[]
  next_steps: string[]
  model: string | null
}

export async function simulateRevenue(
  productId: string,
  payload: RevenueSimulationRequest
): Promise<RevenueSimulationResponse> {
  const response = await apiClient.post<SimulationApi>(
    `/products/${productId}/pricing/simulate`,
    toApiPayload(payload)
  )
  return mapSimulation(response.data)
}

export async function explainRevenueSimulation(
  productId: string,
  payload: RevenueSimulationRequest
): Promise<RevenueSimulationExplanationResponse> {
  const response = await apiClient.post<ExplanationApi>(
    `/products/${productId}/pricing/simulate/explain`,
    toApiPayload(payload)
  )
  return {
    simulation: mapSimulation(response.data.simulation),
    explanation: response.data.explanation,
    summary: response.data.summary,
    risks: response.data.risks,
    nextSteps: response.data.next_steps,
    model: response.data.model,
  }
}

function toApiPayload(payload: RevenueSimulationRequest) {
  return {
    candidate_prices: payload.candidatePrices,
    forecast_horizon_days: payload.forecastHorizonDays,
  }
}

function mapSimulation(data: SimulationApi): RevenueSimulationResponse {
  return {
    sellerId: data.seller_id,
    productId: data.product_id,
    productTitle: data.product_title,
    pricingAnalyticsId: data.pricing_analytics_id,
    currentPrice: toNumber(data.current_price),
    baselineUnits: toNullableNumber(data.baseline_units),
    baselineExpectedRevenue: toNullableNumber(data.baseline_expected_revenue),
    baselineExpectedProfit: toNullableNumber(data.baseline_expected_profit),
    forecastHorizonDays: data.forecast_horizon_days,
    demandMethod: data.demand_method,
    dataStatus: data.data_status,
    confidenceScore: toNumber(data.confidence_score),
    calculatedAt: data.calculated_at,
    scenarios: data.scenarios.map(mapScenario),
    evidence: data.evidence,
  }
}

function mapScenario(data: ScenarioApi): RevenueSimulationScenario {
  return {
    candidatePrice: toNumber(data.candidate_price),
    action: data.action,
    isAllowed: data.is_allowed,
    rejectionReasons: data.rejection_reasons,
    expectedUnitsLower: toNullableNumber(data.expected_units_lower),
    expectedUnits: toNullableNumber(data.expected_units),
    expectedUnitsUpper: toNullableNumber(data.expected_units_upper),
    expectedRevenue: toNullableNumber(data.expected_revenue),
    expectedProfit: toNullableNumber(data.expected_profit),
    revenueImpact: toNullableNumber(data.revenue_impact),
    profitImpact: toNullableNumber(data.profit_impact),
    unitProfit: toNullableNumber(data.unit_profit),
    marginRate: toNullableNumber(data.margin_rate),
    minimumSafePrice: toNullableNumber(data.minimum_safe_price),
    confidenceScore: toNumber(data.confidence_score),
    estimationMethod: data.estimation_method,
    dataStatus: data.data_status,
    evidence: data.evidence,
  }
}

function toNumber(value: string | number): number {
  return typeof value === "number" ? value : Number(value)
}

function toNullableNumber(value: string | number | null): number | null {
  return value === null ? null : toNumber(value)
}
