import { formatCurrency, formatNumber, formatPercent } from "@/utils/formatters"

import type {
  RecommendationAction,
  RecommendationConfidence,
} from "../types/recommendation"

type ActionMeta = {
  label: string
  description: string
  tone: string
}

const actionMetaMap: Record<RecommendationAction, ActionMeta> = {
  LOWER: {
    label: "Lower price",
    description: "Pricing pressure suggests a downward adjustment.",
    tone: "text-amber-700 bg-amber-100/80 border-amber-200",
  },
  RAISE: {
    label: "Raise price",
    description: "Market opportunity supports a higher price.",
    tone: "text-emerald-700 bg-emerald-100/80 border-emerald-200",
  },
  HOLD: {
    label: "Hold price",
    description: "Pricing is within a healthy range.",
    tone: "text-muted-foreground bg-muted/80 border-border",
  },
  REORDER: {
    label: "Reorder stock",
    description: "Inventory risk indicates a restock action.",
    tone: "text-rose-700 bg-rose-100/80 border-rose-200",
  },
}

const confidenceToneMap: Record<RecommendationConfidence, string> = {
  HIGH: "text-emerald-600",
  MEDIUM: "text-amber-600",
  LOW: "text-rose-600",
}

export const getActionMeta = (action: RecommendationAction) => actionMetaMap[action]

export const getConfidenceTone = (confidence: RecommendationConfidence) =>
  confidenceToneMap[confidence]

const recommendationPrice = new Intl.NumberFormat("en-BD", {
  style: "currency",
  currency: "BDT",
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
})

export const formatRecommendationPrice = (value: number) => recommendationPrice.format(value)

export const formatNullableCurrency = (value: number | null | undefined) =>
  value === null || value === undefined ? "Unavailable" : formatCurrency(value)

export const formatNullableNumber = (value: number | null | undefined) =>
  value === null || value === undefined ? "Unavailable" : formatNumber(value)

export const formatNullablePercent = (value: number | null | undefined) =>
  value === null || value === undefined ? "Unavailable" : formatPercent(value)

export const formatScorePercent = (value: number) =>
  formatPercent(Math.min(Math.max(value, 0), 1) * 100)

export const formatSignedPercent = (value: number | null | undefined) => {
  if (value === null || value === undefined) {
    return "Unavailable"
  }
  const sign = value > 0 ? "+" : value < 0 ? "-" : ""
  const magnitude = formatPercent(Math.abs(value))
  return `${sign}${magnitude}`
}
