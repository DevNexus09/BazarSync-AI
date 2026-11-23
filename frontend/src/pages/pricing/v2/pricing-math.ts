import type {
  EstimationMethod,
  MarketPosition,
  PricingPolicy,
  PricingRecommendation,
} from "@/services/pricing-v2-service"
import { formatMoney } from "@/utils/formatters"

import { t } from "./pricing-i18n"

/** Decimal string -> integer paisa. All price stepping happens on integers, never on float taka. */
export function toPaisa(value: string): number {
  const match = /^(-?)(\d+)(?:\.(\d{1,2})\d*)?$/.exec(value.trim())
  if (!match) {
    throw new Error(`Not a money value: ${value}`)
  }
  const [, sign, whole, fraction = ""] = match
  const paisa = Number(whole) * 100 + Number(fraction.padEnd(2, "0"))
  return sign ? -paisa : paisa
}

export function fromPaisa(paisa: number): string {
  const sign = paisa < 0 ? "-" : ""
  const abs = Math.abs(Math.round(paisa))
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`
}

// Without a policy limit the slider still stays within ±30% of today's price.
const DEFAULT_CHANGE_RATE = 0.3

export type SliderBounds = { min: number; max: number; step: number; value: number }

/** Slider range in paisa: snapped to the policy price step and bounded by its change limits. */
export function sliderBounds(currentPrice: string, policy: PricingPolicy | undefined): SliderBounds {
  const current = toPaisa(currentPrice)
  const step = Math.max(1, toPaisa(policy?.priceIncrement ?? "1.00"))
  const decrease = Number(policy?.maximumPriceDecreaseRate ?? DEFAULT_CHANGE_RATE)
  const increase = Number(policy?.maximumPriceIncreaseRate ?? DEFAULT_CHANGE_RATE)
  let low = Math.round(current * (1 - decrease))
  let high = Math.round(current * (1 + increase))
  if (policy?.minimumAllowedPrice) low = Math.max(low, toPaisa(policy.minimumAllowedPrice))
  if (policy?.maximumAllowedPrice) high = Math.min(high, toPaisa(policy.maximumAllowedPrice))
  const min = Math.max(step, Math.ceil(low / step) * step)
  const max = Math.max(min, Math.floor(high / step) * step)
  const value = Math.min(max, Math.max(min, Math.round(current / step) * step))
  return { min, max, step, value }
}

export function elasticityLabel(method: EstimationMethod | undefined, elasticity: unknown): string {
  const value = elasticity == null ? null : Number(elasticity).toFixed(1).replace("-", "−")
  const sources: Partial<Record<EstimationMethod, string>> = {
    HISTORICAL_ELASTICITY: t("sourceHistorical"),
    POOLED_CATEGORY: t("sourcePooled"),
    CATEGORY_PRIOR: t("sourcePrior"),
    CONSERVATIVE_HEURISTIC: t("sourceHeuristic"),
  }
  if (method === "INSUFFICIENT_DATA") return t("sourceInsufficient")
  const source = method ? sources[method] : undefined
  if (!source) return t("sourceUnknown")
  return value ? t("sourceElasticity", { source, value }) : source
}

/** "9% above market", "8% below market", "At market", "No market data". */
export function positionLabel(position: MarketPosition, rate: string | null): string {
  const percent = rate == null ? null : Math.abs(Math.round(Number(rate) * 100))
  switch (position) {
    case "ABOVE_MARKET":
      return t("positionAbove", { percent: percent ?? 0 })
    case "BELOW_MARKET":
      return t("positionBelow", { percent: percent ?? 0 })
    case "AT_MARKET":
      return t("positionAt")
    default:
      return t("positionNone")
  }
}

export function percentLabel(rate: string | null | undefined): string | null {
  return rate == null ? null : `${(Number(rate) * 100).toFixed(1)}%`
}

/** Readable reason text for MarginGuard rejection codes. */
export function rejectionLabel(code: string): string {
  const known: Record<string, string> = {
    BELOW_MINIMUM_SAFE_PRICE: t("rejectBelowSafe"),
    NEGATIVE_UNIT_PROFIT: t("rejectLoss"),
    BELOW_MINIMUM_MARGIN: t("rejectMargin"),
    BELOW_MINIMUM_UNIT_PROFIT: t("rejectUnitProfit"),
    EXCEEDS_MAXIMUM_DECREASE: t("rejectDecrease"),
    EXCEEDS_MAXIMUM_INCREASE: t("rejectIncrease"),
    BELOW_ABSOLUTE_MINIMUM: t("rejectAbsMin"),
    ABOVE_ABSOLUTE_MAXIMUM: t("rejectAbsMax"),
    INVALID_MARKETPLACE_INCREMENT: t("rejectIncrement"),
    MISSING_COST_DATA: t("rejectCost"),
    MISSING_FEE_DATA: t("rejectFees"),
  }
  return known[code] ?? code.toLowerCase().replace(/_/g, " ")
}

export function confidenceLabel(score: string): string {
  const value = Number(score)
  return value >= 70 ? t("confidenceHigh") : value >= 40 ? t("confidenceMedium") : t("confidenceLow")
}

export type ProfitPoint = {
  price: number
  profit: number
  priceText: string
  profitText: string
  allowed: boolean
  reasons: string[]
}

/** Candidate prices with a profit estimate, for the profit curve (numbers only position the marks). */
export function profitCurvePoints(recommendation: PricingRecommendation | null): ProfitPoint[] {
  return (recommendation?.candidates ?? [])
    .filter((item) => item.expectedProfit != null)
    .map((item) => ({
      price: Number(item.candidatePrice),
      profit: Number(item.expectedProfit),
      priceText: formatMoney(item.candidatePrice) ?? item.candidatePrice,
      profitText: formatMoney(item.expectedProfit) ?? "",
      allowed: item.isAllowed,
      reasons: item.rejectionReasons.map(rejectionLabel),
    }))
    .sort((a, b) => a.price - b.price)
}
