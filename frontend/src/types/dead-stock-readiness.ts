export type DeadStockReadinessStatus =
  | "OK"
  | "MISSING"
  | "UNAVAILABLE"
  | "STALE"
  | "INSUFFICIENT"
  | "PENDING_CALCULATION"
  | "ACTION_REQUIRED"
  | "OPTIONAL"
  | "ERROR"

export type DeadStockReadinessCheck = {
  status: DeadStockReadinessStatus
  reasonCode: string | null
  message: string
  blocking: boolean
  currentValue: unknown
  nextAction: string | null
  href: string | null
}

export type DeadStockReadinessAction = {
  key: string
  label: string
  description: string
  href: string | null
  implemented: boolean
  priority: number
}

export type DeadStockReadiness = {
  productId: string
  productName: string
  ready: boolean
  canClassifyDeadStock: boolean
  canScoreRisk: boolean
  canEstimateLockedCapital: boolean
  canGenerateRecoveryRecommendation: boolean
  canEstimatePotentialRecovery: boolean
  checks: Record<string, DeadStockReadinessCheck>
  blockingReasons: string[]
  nonBlockingReasons: string[]
  nextActions: DeadStockReadinessAction[]
  recommendedSetupOrder: string[]
  lastCheckedAt: string
}

export type DeadStockRecalculationResult = {
  productId: string
  enqueued: boolean
  message: string
  readiness: DeadStockReadiness
}
