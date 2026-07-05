export type DeadStockClassification =
  | "HEALTHY"
  | "SLOW_MOVING"
  | "AT_RISK"
  | "DEAD_STOCK"
  | "INSUFFICIENT_DATA"

export type DeadStockRiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
export type DeadStockDataStatus = "SUFFICIENT" | "LIMITED" | "INSUFFICIENT"
export type RecoveryAction =
  | "BUNDLE"
  | "DISCOUNT"
  | "FLASH_SALE"
  | "SEO_FIX"
  | "HOLD"
  | "MANUAL_REVIEW"

export type DeadStockSummary = {
  totalProductsWithInventory: number
  healthyProductCount: number
  slowMovingCount: number
  atRiskCount: number
  deadStockCount: number
  criticalRiskCount: number
  totalEligibleDeadStockUnits: number
  totalLockedCapital: number | null
  lockedCapitalCurrency: string | null
  estimatedRecoverableCash: number | null
  recoverableCashCurrency: string | null
  productsWithInsufficientData: number
  productsRequiringManualReview: number
  lastCalculationTime: string | null
  formulaVersion: string | null
  monetaryTotalsComparable: boolean
  forecastHorizonDays: number | null
  ageDistribution: Record<string, number>
}

export type DeadStockProduct = {
  productId: string
  productName: string
  category: string | null
  currentStock: number
  eligibleUnsoldQuantity: number | null
  inventoryAgeDays: number | null
  inventoryAgeIsEstimated: boolean
  ageSource: string | null
  daysSinceLastSale: number | null
  classification: DeadStockClassification | null
  riskScore: number | null
  riskLevel: DeadStockRiskLevel | null
  lockedCapital: number | null
  lockedCapitalCurrency: string | null
  primaryRecommendation: RecoveryAction | null
  recommendationStatus: string | null
  potentialRecovery: number | null
  potentialRecoveryLow: number | null
  potentialRecoveryHigh: number | null
  dataStatus: DeadStockDataStatus | null
  lastCalculatedAt: string | null
}

export type DeadStockProductPage = {
  items: DeadStockProduct[]
  total: number
  limit: number
  offset: number
}

export type DeadStockFilters = {
  classification?: DeadStockClassification | "ALL"
  riskLevel?: DeadStockRiskLevel | "ALL"
  category?: string
  marketplace?: string
  minAgeDays?: number
  minLockedCapital?: number
  recommendationAction?: RecoveryAction | "ALL"
  dataStatus?: DeadStockDataStatus | "ALL"
  sort?: "risk" | "age" | "locked_capital" | "potential_recovery"
  limit?: number
  offset?: number
}

export type ProductDeadStockIntelligence = {
  productId: string
  productName: string
  category: string | null
  currentInventory: number
  eligibleUnsoldQuantity: number | null
  inventoryAgeDays: number | null
  inventoryAgeIsEstimated: boolean
  inventoryAgeState: string | null
  ageSource: string | null
  daysSinceLastSale: number | null
  dailySalesRate: number | null
  velocityDataStatus: string | null
  visibilityStatus: string | null
  classification: DeadStockClassification | null
  riskScore: number | null
  riskLevel: DeadStockRiskLevel | null
  triggeredRules: string[]
  lockedCapital: number | null
  lockedCapitalCurrency: string | null
  primaryRecoveryRecommendation: RecoveryAction | null
  recommendedDiscountRate: number | null
  recommendedPrice: number | null
  potentialRecoveredCashLow: number | null
  potentialRecoveredCash: number | null
  potentialRecoveredCashHigh: number | null
  confidence: number | null
  dataStatus: DeadStockDataStatus | null
  lastUpdatedAt: string | null
  formulaVersion: string | null
  recoveryRecommendation: Record<string, unknown> | null
  capitalRecovery: Record<string, unknown> | null
  evidence: Record<string, unknown>
}

export type RecoverySimulationInput = {
  action: RecoveryAction
  candidateDiscount?: number
  candidatePrice?: number
  durationDays?: number
  eligibleQuantity?: number
}
