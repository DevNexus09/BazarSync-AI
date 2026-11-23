export type InventoryRiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"

export type InventoryDataStatus = "SUFFICIENT" | "LIMITED" | "INSUFFICIENT"

export type ReorderAction =
  | "NO_ACTION"
  | "MONITOR"
  | "REORDER"
  | "URGENT_REORDER"
  | "EXPEDITE"

export type InventoryIntelligenceSummary = {
  totalActiveProducts: number
  lowRiskProducts: number
  mediumRiskProducts: number
  highRiskProducts: number
  criticalRiskProducts: number
  insufficientDataProducts: number
  productsRequiringReorder: number
  productsAlreadyOutOfStock: number
  lastCalculationTime: string | null
  dataFreshnessStatus: string
}

export type InventoryIntelligenceItem = {
  productId: string
  productName: string
  category: string | null
  riskLevel: InventoryRiskLevel | null
  riskScore: number | null
  dataStatus: InventoryDataStatus | string | null
  daysRemaining: number | null
  predictedStockoutDate: string | null
  reorderAction: ReorderAction | string | null
  recommendationStatus: string | null
  recommendedQuantity: number | null
  reorderDeadline: string | null
  calculationVersion: string | null
  asOfDate: string | null
  lastUpdatedAt: string | null
  reorderRecommendationId?: string | null
  supplierLeadTimeDays?: number | null
  supplierLeadTimeDefaulted?: boolean | null
}

export type InventoryIntelligencePage<T = InventoryIntelligenceItem> = {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type ProductInventoryIntelligence = {
  productId: string
  productName: string
  category: string | null
  latestInventorySnapshotId: string | null
  inventorySnapshotDate: string | null
  quantityOnHand: number | null
  quantityReserved: number | null
  quantityAvailable: number | null
  quantityIncoming: number | null
  dailySalesRate: number | null
  velocityWindowDays: number | null
  velocityDataStatus: string | null
  daysRemaining: number | null
  predictedStockoutDate: string | null
  stockoutPredictionStatus: string | null
  supplierLeadTimeDays: number | null
  safetyBufferDays: number | null
  inventoryRiskScore: number | null
  riskLevel: InventoryRiskLevel | null
  reorderAction: ReorderAction | string | null
  recommendedQuantity: number | null
  reorderDeadline: string | null
  confidenceScore: number | null
  dataStatus: InventoryDataStatus | string | null
  explanation: string | null
  calculationVersion: string | null
  asOfDate: string | null
  lastUpdatedAt: string | null
  metadata: Record<string, unknown> | null
  reorderRecommendationId?: string | null
  recommendationStatus?: string | null
  supplierLeadTimeDefaulted?: boolean | null
  safetyStockUnits?: number | null
  safetyStockServiceLevel?: number | null
}

export type InventoryWorkflowResponse = {
  workflowId: string
  scope: string
  sellerId: string | null
  productId?: string | null
  asOfDate?: string | null
}
