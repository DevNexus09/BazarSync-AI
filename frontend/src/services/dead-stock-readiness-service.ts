import apiClient from "@/api/client"
import type {
  DeadStockReadiness,
  DeadStockReadinessAction,
  DeadStockReadinessCheck,
  DeadStockRecalculationResult,
} from "@/types/dead-stock-readiness"

type ApiReadinessCheck = {
  status: DeadStockReadinessCheck["status"]
  reason_code?: string | null
  message: string
  blocking: boolean
  current_value?: unknown
  next_action?: string | null
  href?: string | null
}

type ApiReadinessAction = {
  key: string
  label: string
  description: string
  href?: string | null
  implemented: boolean
  priority: number
}

type ApiReadiness = {
  product_id: string
  product_name: string
  ready: boolean
  can_classify_dead_stock: boolean
  can_score_risk: boolean
  can_estimate_locked_capital: boolean
  can_generate_recovery_recommendation: boolean
  can_estimate_potential_recovery: boolean
  checks: Record<string, ApiReadinessCheck>
  blocking_reasons: string[]
  non_blocking_reasons: string[]
  next_actions: ApiReadinessAction[]
  recommended_setup_order: string[]
  last_checked_at: string
}

type ApiRecalculation = {
  product_id: string
  enqueued: boolean
  message: string
  readiness: ApiReadiness
}

export async function getDeadStockReadiness(productId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<ApiReadiness>(
    `/products/${productId}/dead-stock/readiness`,
    { signal }
  )
  return mapReadiness(data)
}

export async function recalculateDeadStock(productId: string) {
  const { data } = await apiClient.post<ApiRecalculation>(
    `/products/${productId}/dead-stock/recalculate`
  )
  return {
    productId: data.product_id,
    enqueued: data.enqueued,
    message: data.message,
    readiness: mapReadiness(data.readiness),
  } satisfies DeadStockRecalculationResult
}

function mapReadiness(data: ApiReadiness): DeadStockReadiness {
  return {
    productId: data.product_id,
    productName: data.product_name,
    ready: data.ready,
    canClassifyDeadStock: data.can_classify_dead_stock,
    canScoreRisk: data.can_score_risk,
    canEstimateLockedCapital: data.can_estimate_locked_capital,
    canGenerateRecoveryRecommendation: data.can_generate_recovery_recommendation,
    canEstimatePotentialRecovery: data.can_estimate_potential_recovery,
    checks: Object.fromEntries(
      Object.entries(data.checks).map(([key, check]) => [key, mapCheck(check)])
    ),
    blockingReasons: data.blocking_reasons ?? [],
    nonBlockingReasons: data.non_blocking_reasons ?? [],
    nextActions: (data.next_actions ?? []).map(mapAction),
    recommendedSetupOrder: data.recommended_setup_order ?? [],
    lastCheckedAt: data.last_checked_at,
  }
}

function mapCheck(check: ApiReadinessCheck): DeadStockReadinessCheck {
  return {
    status: check.status,
    reasonCode: check.reason_code ?? null,
    message: check.message,
    blocking: check.blocking,
    currentValue: check.current_value ?? null,
    nextAction: check.next_action ?? null,
    href: check.href ?? null,
  }
}

function mapAction(action: ApiReadinessAction): DeadStockReadinessAction {
  return {
    key: action.key,
    label: action.label,
    description: action.description,
    href: action.href ?? null,
    implemented: action.implemented,
    priority: action.priority,
  }
}
