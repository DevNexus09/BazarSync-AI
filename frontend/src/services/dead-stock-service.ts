import apiClient from "@/api/client"
import type {
  DeadStockFilters,
  DeadStockProduct,
  DeadStockProductPage,
  DeadStockSummary,
  ProductDeadStockIntelligence,
  RecoverySimulationInput,
} from "@/types/dead-stock"

const toNumberOrNull = (value?: number | string | null) => {
  if (value == null || value === "") return null
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

const params = (filters: DeadStockFilters) => ({
  classification:
    filters.classification && filters.classification !== "ALL"
      ? filters.classification
      : undefined,
  risk_level:
    filters.riskLevel && filters.riskLevel !== "ALL"
      ? filters.riskLevel
      : undefined,
  category: filters.category || undefined,
  marketplace: filters.marketplace || undefined,
  min_age_days: filters.minAgeDays,
  min_locked_capital: filters.minLockedCapital,
  recommendation_action:
    filters.recommendationAction && filters.recommendationAction !== "ALL"
      ? filters.recommendationAction
      : undefined,
  data_status:
    filters.dataStatus && filters.dataStatus !== "ALL"
      ? filters.dataStatus
      : undefined,
  sort: filters.sort,
  limit: filters.limit,
  offset: filters.offset,
})

type DeadStockProductApiItem = {
  product_id: string
  product_name: string
  category?: string | null
  current_stock: number
  eligible_unsold_quantity?: number | null
  inventory_age_days?: number | null
  inventory_age_is_estimated?: boolean | null
  age_source?: string | null
  days_since_last_sale?: number | null
  classification?: DeadStockProduct["classification"]
  risk_score?: number | string | null
  risk_level?: DeadStockProduct["riskLevel"]
  locked_capital?: number | string | null
  locked_capital_currency?: string | null
  primary_recommendation?: DeadStockProduct["primaryRecommendation"]
  recommendation_status?: string | null
  potential_recovery?: number | string | null
  potential_recovery_low?: number | string | null
  potential_recovery_high?: number | string | null
  data_status?: DeadStockProduct["dataStatus"]
  last_calculated_at?: string | null
}

export async function getDeadStockSummary(signal?: AbortSignal) {
  const { data } = await apiClient.get("/dead-stock/summary", { signal })
  return {
    totalProductsWithInventory: data.total_products_with_inventory,
    healthyProductCount: data.healthy_product_count,
    slowMovingCount: data.slow_moving_count,
    atRiskCount: data.at_risk_count,
    deadStockCount: data.dead_stock_count,
    criticalRiskCount: data.critical_risk_count,
    totalEligibleDeadStockUnits: data.total_eligible_dead_stock_units,
    totalLockedCapital: toNumberOrNull(data.total_locked_capital),
    lockedCapitalCurrency: data.locked_capital_currency ?? null,
    estimatedRecoverableCash: toNumberOrNull(data.estimated_recoverable_cash),
    recoverableCashCurrency: data.recoverable_cash_currency ?? null,
    productsWithInsufficientData: data.products_with_insufficient_data,
    productsRequiringManualReview: data.products_requiring_manual_review,
    lastCalculationTime: data.last_calculation_time ?? null,
    formulaVersion: data.formula_version ?? null,
    monetaryTotalsComparable: Boolean(data.monetary_totals_comparable),
    forecastHorizonDays: data.forecast_horizon_days ?? null,
    ageDistribution: data.age_distribution ?? {},
  } satisfies DeadStockSummary
}

const mapProduct = (item: DeadStockProductApiItem): DeadStockProduct => ({
  productId: item.product_id,
  productName: item.product_name,
  category: item.category ?? null,
  currentStock: item.current_stock,
  eligibleUnsoldQuantity: item.eligible_unsold_quantity ?? null,
  inventoryAgeDays: item.inventory_age_days ?? null,
  inventoryAgeIsEstimated: Boolean(item.inventory_age_is_estimated),
  ageSource: item.age_source ?? null,
  daysSinceLastSale: item.days_since_last_sale ?? null,
  classification: item.classification ?? null,
  riskScore: toNumberOrNull(item.risk_score),
  riskLevel: item.risk_level ?? null,
  lockedCapital: toNumberOrNull(item.locked_capital),
  lockedCapitalCurrency: item.locked_capital_currency ?? null,
  primaryRecommendation: item.primary_recommendation ?? null,
  recommendationStatus: item.recommendation_status ?? null,
  potentialRecovery: toNumberOrNull(item.potential_recovery),
  potentialRecoveryLow: toNumberOrNull(item.potential_recovery_low),
  potentialRecoveryHigh: toNumberOrNull(item.potential_recovery_high),
  dataStatus: item.data_status ?? null,
  lastCalculatedAt: item.last_calculated_at ?? null,
})

export async function getDeadStockProducts(
  filters: DeadStockFilters & { signal?: AbortSignal }
) {
  const { data } = await apiClient.get("/dead-stock/products", {
    params: params(filters),
    signal: filters.signal,
  })
  return {
    items: data.items.map(mapProduct),
    total: data.total,
    limit: data.limit,
    offset: data.offset,
  } satisfies DeadStockProductPage
}

export async function getProductDeadStockIntelligence(
  productId: string,
  signal?: AbortSignal
) {
  const { data } = await apiClient.get(
    `/products/${productId}/dead-stock/intelligence`,
    { signal }
  )
  return {
    productId: data.product_id,
    productName: data.product_name,
    category: data.category ?? null,
    currentInventory: data.current_inventory,
    eligibleUnsoldQuantity: data.eligible_unsold_quantity ?? null,
    inventoryAgeDays: data.inventory_age_days ?? null,
    inventoryAgeIsEstimated: Boolean(data.inventory_age_is_estimated),
    inventoryAgeState: data.inventory_age_state ?? null,
    ageSource: data.age_source ?? null,
    daysSinceLastSale: data.days_since_last_sale ?? null,
    dailySalesRate: toNumberOrNull(data.daily_sales_rate),
    velocityDataStatus: data.velocity_data_status ?? null,
    visibilityStatus: data.visibility_status ?? null,
    classification: data.classification ?? null,
    riskScore: toNumberOrNull(data.risk_score),
    riskLevel: data.risk_level ?? null,
    triggeredRules: data.triggered_rules ?? [],
    lockedCapital: toNumberOrNull(data.locked_capital),
    lockedCapitalCurrency: data.locked_capital_currency ?? null,
    primaryRecoveryRecommendation: data.primary_recovery_recommendation ?? null,
    recommendedDiscountRate: toNumberOrNull(data.recommended_discount_rate),
    recommendedPrice: toNumberOrNull(data.recommended_price),
    potentialRecoveredCashLow: toNumberOrNull(data.potential_recovered_cash_low),
    potentialRecoveredCash: toNumberOrNull(data.potential_recovered_cash),
    potentialRecoveredCashHigh: toNumberOrNull(data.potential_recovered_cash_high),
    confidence: toNumberOrNull(data.confidence),
    dataStatus: data.data_status ?? null,
    lastUpdatedAt: data.last_updated_at ?? null,
    formulaVersion: data.formula_version ?? null,
    recoveryRecommendation: data.recovery_recommendation ?? null,
    capitalRecovery: data.capital_recovery ?? null,
    evidence: data.evidence ?? {},
  } satisfies ProductDeadStockIntelligence
}

export async function simulateCapitalRecovery(
  productId: string,
  input: RecoverySimulationInput
) {
  const { data } = await apiClient.post(
    `/products/${productId}/dead-stock/recovery-simulations`,
    {
      action: input.action,
      candidate_discount: input.candidateDiscount,
      candidate_price: input.candidatePrice,
      duration_days: input.durationDays,
      eligible_quantity: input.eligibleQuantity,
    }
  )
  return {
    productId: data.product_id,
    productName: "",
    category: null,
    currentInventory: 0,
    eligibleUnsoldQuantity: data.eligible_quantity ?? null,
    inventoryAgeDays: null,
    inventoryAgeIsEstimated: false,
    inventoryAgeState: null,
    ageSource: null,
    daysSinceLastSale: null,
    dailySalesRate: null,
    velocityDataStatus: null,
    visibilityStatus: null,
    classification: null,
    riskScore: null,
    riskLevel: null,
    triggeredRules: [],
    lockedCapital: toNumberOrNull(data.locked_capital),
    lockedCapitalCurrency: data.currency ?? null,
    primaryRecoveryRecommendation: data.recommended_action ?? null,
    recommendedDiscountRate: null,
    recommendedPrice: toNumberOrNull(data.candidate_price),
    potentialRecoveredCashLow: toNumberOrNull(data.potential_recovered_cash?.low),
    potentialRecoveredCash: toNumberOrNull(data.potential_recovered_cash?.central),
    potentialRecoveredCashHigh: toNumberOrNull(data.potential_recovered_cash?.high),
    confidence: toNumberOrNull(data.confidence_score),
    dataStatus: null,
    lastUpdatedAt: data.calculated_at ?? null,
    formulaVersion: data.calculation_version ?? null,
    recoveryRecommendation: null,
    capitalRecovery: {
      estimate_status: data.estimate_status,
      estimation_method: data.estimation_method,
      contribution_recovered: data.contribution_recovered,
      capital_recovery_ratio: data.capital_recovery_ratio,
    },
    evidence: data.evidence ?? {},
  } satisfies ProductDeadStockIntelligence
}
