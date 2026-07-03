import type { RevenueSimulationResponse } from "@/types/pricing-simulator"

const MISSING_FEE_PATTERN = /missing[\s_-]*fee[\s_-]*data/i

export type MarketplaceFeeSetupParams = {
  productId?: string
  marketplace?: string
  category?: string
  currency?: string
}

export function isMissingFeeDataReason(reason: string) {
  return MISSING_FEE_PATTERN.test(reason)
}

export function simulationNeedsFeeSetup(
  simulation?: RevenueSimulationResponse | null
) {
  if (!simulation || simulation.scenarios.length === 0) {
    return false
  }

  const blockedByMissingFee = simulation.scenarios.filter((scenario) =>
    scenario.rejectionReasons.some(isMissingFeeDataReason)
  ).length

  return blockedByMissingFee > 0 && blockedByMissingFee >= Math.ceil(simulation.scenarios.length / 2)
}

export function buildMarketplaceFeeSetupPath(params: MarketplaceFeeSetupParams) {
  const search = new URLSearchParams()
  if (params.productId) search.set("productId", params.productId)
  if (params.marketplace) search.set("marketplace", params.marketplace)
  if (params.category) search.set("category", params.category)
  if (params.currency) search.set("currency", params.currency)

  const query = search.toString()
  return `/app/pricing/fee-setup${query ? `?${query}` : ""}`
}

export function percentToRate(percent: number) {
  return Number((percent / 100).toFixed(6))
}
