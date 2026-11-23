import apiClient from "@/api/client"

/** Money and rates stay as the API's Decimal strings; format with formatMoney, never add them as floats. */
type Dec = string

export type MarketPosition = "ABOVE_MARKET" | "AT_MARKET" | "BELOW_MARKET" | "NO_MARKET_DATA"
export type PricingAction = "PRICE_LOWER" | "PRICE_RAISE" | "HOLD"
export type RecommendationStatus =
  | "OPEN"
  | "ACKNOWLEDGED"
  | "DISMISSED"
  | "EXPIRED"
  | "SUPERSEDED"
  | "INSUFFICIENT_DATA"
export type AnalyticsDataStatus = "SUFFICIENT" | "LIMITED" | "INSUFFICIENT" | "STALE"
export type EstimationMethod =
  | "HISTORICAL_ELASTICITY"
  | "CATEGORY_PRIOR"
  | "CONSERVATIVE_HEURISTIC"
  | "POOLED_CATEGORY"
  | "INSUFFICIENT_DATA"

export type PricingOverviewRow = {
  productId: string
  title: string
  sku: string | null
  category: string | null
  currentPrice: Dec
  currency: string
  analyticsId: string | null
  analyticsCalculatedAt: string | null
  dataStatus: AnalyticsDataStatus | null
  marketMedianPrice: Dec | null
  competitorCount: number
  priceVsMedianRate: Dec | null
  position: MarketPosition
  minimumSafePrice: Dec | null
  marginAtRisk: boolean
  hasPricingPolicy: boolean
  recommendation: {
    id: string
    action: PricingAction
    recommendedPrice: Dec
    status: RecommendationStatus
    confidenceScore: Dec
    profitImpact: Dec | null
    generatedAt: string
    isActionable: boolean
  } | null
}

export type PricingOverview = {
  items: PricingOverviewRow[]
  total: number
  summary: {
    productCount: number
    pricedAboveMarket: number
    pricedBelowMarket: number
    marginAtRisk: number
    recommendationsWaiting: number
    withoutAnalytics: number
    productsWithPricingPolicy: number
    productsWithCompetitorData: number
    lastCalculatedAt: string | null
  }
}

export type PricingAnalytics = {
  id: string
  currentPrice: Dec
  unitCost: Dec
  percentageFeeRate: Dec
  fixedFeeAmount: Dec
  currentUnitProfit: Dec
  currentMarginRate: Dec | null
  minimumSafePrice: Dec
  competitorMinPrice: Dec | null
  competitorQ1Price: Dec | null
  competitorMedianPrice: Dec | null
  competitorQ3Price: Dec | null
  competitorMaxPrice: Dec | null
  competitorCount: number
  inStockCompetitorCount: number
  dataStatus: AnalyticsDataStatus
  confidenceScore: Dec
  calculationVersion: string
  calculatedAt: string
  evidence: Record<string, unknown>
}

export type PriceCandidate = {
  candidatePrice: Dec
  isAllowed: boolean
  rejectionReasons: string[]
  expectedProfit: Dec | null
  expectedUnits: Dec | null
}

export type PricingRecommendation = {
  id: string
  action: PricingAction
  currentPrice: Dec
  recommendedPrice: Dec
  minimumSafePrice: Dec | null
  expectedUnits: Dec | null
  expectedProfit: Dec | null
  baselineExpectedProfit: Dec | null
  profitImpact: Dec | null
  revenueImpact: Dec | null
  marginRate: Dec | null
  confidenceScore: Dec
  estimationMethod: EstimationMethod
  status: RecommendationStatus
  formulaVersion: string
  generatedAt: string
  expiresAt: string | null
  candidates: PriceCandidate[]
  evidence: Record<string, unknown>
}

export type PricingPolicy = {
  isDefault: boolean
  minimumMarginRate: Dec | null
  minimumUnitProfit: Dec
  maximumPriceDecreaseRate: Dec | null
  maximumPriceIncreaseRate: Dec | null
  minimumAllowedPrice: Dec | null
  maximumAllowedPrice: Dec | null
  priceIncrement: Dec
}

type Api = Record<string, unknown>
const str = (value: unknown): string | null => (value == null ? null : String(value))

export async function getPricingOverview(): Promise<PricingOverview> {
  // shortcut: one page of 200 rows, searched/sorted in the browser; page through the API if sellers exceed it.
  const { data } = await apiClient.get("/pricing/overview", { params: { limit: 200, offset: 0 } })
  const summary = data.summary
  return {
    total: data.total,
    items: (data.items as Api[]).map((row) => {
      const rec = row.recommendation as Api | null
      return {
        productId: String(row.product_id),
        title: String(row.title),
        sku: str(row.sku),
        category: str(row.category),
        currentPrice: String(row.current_price),
        currency: String(row.currency ?? "BDT"),
        analyticsId: str(row.analytics_id),
        analyticsCalculatedAt: str(row.analytics_calculated_at),
        dataStatus: row.data_status as AnalyticsDataStatus | null,
        marketMedianPrice: str(row.market_median_price),
        competitorCount: Number(row.competitor_count),
        priceVsMedianRate: str(row.price_vs_median_rate),
        position: row.position as MarketPosition,
        minimumSafePrice: str(row.minimum_safe_price),
        marginAtRisk: Boolean(row.margin_at_risk),
        hasPricingPolicy: Boolean(row.has_pricing_policy),
        recommendation: rec
          ? {
              id: String(rec.id),
              action: rec.action as PricingAction,
              recommendedPrice: String(rec.recommended_price),
              status: rec.recommendation_status as RecommendationStatus,
              confidenceScore: String(rec.confidence_score),
              profitImpact: str(rec.profit_impact),
              generatedAt: String(rec.generated_at),
              isActionable: Boolean(rec.is_actionable),
            }
          : null,
      }
    }),
    summary: {
      productCount: summary.product_count,
      pricedAboveMarket: summary.priced_above_market,
      pricedBelowMarket: summary.priced_below_market,
      marginAtRisk: summary.margin_at_risk,
      recommendationsWaiting: summary.recommendations_waiting,
      withoutAnalytics: summary.without_analytics,
      productsWithPricingPolicy: summary.products_with_pricing_policy,
      productsWithCompetitorData: summary.products_with_competitor_data,
      lastCalculatedAt: summary.last_calculated_at,
    },
  }
}

function mapAnalytics(row: Api): PricingAnalytics {
  return {
    id: String(row.id),
    currentPrice: String(row.current_price),
    unitCost: String(row.unit_cost),
    percentageFeeRate: String(row.percentage_fee_rate),
    fixedFeeAmount: String(row.fixed_fee_amount),
    currentUnitProfit: String(row.current_unit_profit),
    currentMarginRate: str(row.current_margin_rate),
    minimumSafePrice: String(row.minimum_safe_price),
    competitorMinPrice: str(row.competitor_min_price),
    competitorQ1Price: str(row.competitor_q1_price),
    competitorMedianPrice: str(row.competitor_median_price),
    competitorQ3Price: str(row.competitor_q3_price),
    competitorMaxPrice: str(row.competitor_max_price),
    competitorCount: Number(row.competitor_count),
    inStockCompetitorCount: Number(row.in_stock_competitor_count),
    dataStatus: row.data_status as AnalyticsDataStatus,
    confidenceScore: String(row.confidence_score),
    calculationVersion: String(row.calculation_version),
    calculatedAt: String(row.calculated_at),
    evidence: (row.evidence as Record<string, unknown>) ?? {},
  }
}

export async function getLatestPricingAnalytics(productId: string): Promise<PricingAnalytics | null> {
  const { data } = await apiClient.get(`/products/${productId}/pricing/analytics`)
  return data.item ? mapAnalytics(data.item) : null
}

export async function getPricingAnalyticsHistory(productId: string): Promise<PricingAnalytics[]> {
  const { data } = await apiClient.get(`/products/${productId}/pricing/analytics/history`, {
    params: { limit: 60 },
  })
  return (data.items as Api[]).map(mapAnalytics)
}

/** Recalculates the snapshot and a fresh recommendation. Never changes the live price. */
export async function refreshProductPricing(productId: string): Promise<void> {
  await apiClient.post(`/products/${productId}/pricing/analytics`)
  await apiClient.post(`/products/${productId}/pricing/recommendations`)
}

function mapRecommendation(row: Api): PricingRecommendation {
  const evidence = (row.evidence as Record<string, unknown>) ?? {}
  const candidates = Array.isArray(evidence.candidates) ? (evidence.candidates as Api[]) : []
  return {
    id: String(row.id),
    action: row.action as PricingAction,
    currentPrice: String(row.current_price),
    recommendedPrice: String(row.recommended_price),
    minimumSafePrice: str(row.minimum_safe_price),
    expectedUnits: str(row.expected_units),
    expectedProfit: str(row.expected_profit),
    baselineExpectedProfit: str(row.baseline_expected_profit),
    profitImpact: str(row.profit_impact),
    revenueImpact: str(row.revenue_impact),
    marginRate: str(row.margin_rate),
    confidenceScore: String(row.confidence_score),
    estimationMethod: row.estimation_method as EstimationMethod,
    status: row.recommendation_status as RecommendationStatus,
    formulaVersion: String(row.formula_version),
    generatedAt: String(row.generated_at),
    expiresAt: str(row.expires_at),
    candidates: candidates.map((item) => ({
      candidatePrice: String(item.candidate_price),
      isAllowed: Boolean(item.is_allowed),
      rejectionReasons: Array.isArray(item.rejection_reasons) ? item.rejection_reasons.map(String) : [],
      expectedProfit: str(item.expected_profit),
      expectedUnits: str(item.expected_units),
    })),
    evidence,
  }
}

export async function getLatestPricingRecommendation(productId: string): Promise<PricingRecommendation | null> {
  const { data } = await apiClient.get(`/products/${productId}/pricing/recommendations/latest`)
  return data.item ? mapRecommendation(data.item) : null
}

/** Records the seller's decision only; the marketplace price is changed by the seller. */
export async function setPricingRecommendationStatus(
  recommendationId: string,
  decision: "acknowledge" | "dismiss",
): Promise<PricingRecommendation> {
  const { data } = await apiClient.post(`/pricing/recommendations/${recommendationId}/${decision}`)
  return mapRecommendation(data)
}

export async function getPricingPolicy(productId: string): Promise<PricingPolicy> {
  const { data } = await apiClient.get(`/pricing-policies/products/${productId}`)
  return {
    isDefault: Boolean(data.is_default),
    minimumMarginRate: str(data.minimum_margin_rate),
    minimumUnitProfit: String(data.minimum_unit_profit),
    maximumPriceDecreaseRate: str(data.maximum_price_decrease_rate),
    maximumPriceIncreaseRate: str(data.maximum_price_increase_rate),
    minimumAllowedPrice: str(data.minimum_allowed_price),
    maximumAllowedPrice: str(data.maximum_allowed_price),
    priceIncrement: String(data.price_increment),
  }
}

/** Queues the seller-wide pricing analytics workflow (Celery); results arrive asynchronously. */
export async function recalculateAllPricing(): Promise<void> {
  await apiClient.post("/pricing/analytics/workflow")
}
