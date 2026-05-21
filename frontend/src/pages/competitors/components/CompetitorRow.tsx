import { useState } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { formatCurrency, formatNumber, formatPercent } from "@/utils/formatters"

import type { Competitor } from "../types/competitor.types"

type CompetitorRowProps = {
  competitor: Competitor
  variant?: "table" | "card"
}

const formatMetric = (value: number | null, formatter: (value: number) => string) =>
  value === null || Number.isNaN(value) ? "—" : formatter(value)

const formatPercentScore = (value: number | null) =>
  value === null || Number.isNaN(value) ? "—" : formatPercent(value * 100)

const formatSoldCount = (value: number | string | null) => {
  if (value === null || value === undefined) {
    return "—"
  }
  return typeof value === "number" ? formatNumber(value) : value
}

const getSimilarityTone = (score: number | null) => {
  if (score === null || Number.isNaN(score)) {
    return "text-muted-foreground"
  }
  if (score >= 0.8) {
    return "text-emerald-600"
  }
  if (score >= 0.6) {
    return "text-amber-500"
  }
  return "text-rose-600"
}

const getStockBadgeStyle = (status: string) => {
  const normalized = status.toLowerCase()
  if (normalized.includes("out") || normalized.includes("unavailable")) {
    return "border-rose-200 bg-rose-50 text-rose-700"
  }
  if (normalized.includes("low")) {
    return "border-amber-200 bg-amber-50 text-amber-700"
  }
  return "border-emerald-200 bg-emerald-50 text-emerald-700"
}

export function CompetitorRow({ competitor, variant = "table" }: CompetitorRowProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const similarityValue = competitor.matchConfidence ?? competitor.similarityScore
  const similarityTone = getSimilarityTone(similarityValue ?? null)
  const stockBadgeStyle = getStockBadgeStyle(competitor.stockStatus)
  const attributes = competitor.attributes ?? {}
  const matchedKeys =
    competitor.matchedAttributes && competitor.matchedAttributes.length > 0
      ? competitor.matchedAttributes
      : Object.keys(attributes)
  const attributeEntries = matchedKeys
    .map((key) => [key, attributes[key]] as const)
    .filter(([, value]) => value)
  const shownAttributes = attributeEntries.slice(0, 4)
  const viewButton = competitor.productUrl ? (
    <Button size="sm" variant="outline" asChild>
      <a href={competitor.productUrl} target="_blank" rel="noreferrer">
        View
      </a>
    </Button>
  ) : (
    <span className="text-xs text-muted-foreground">No link</span>
  )

  if (variant === "card") {
    return (
      <div className="rounded-xl border bg-background p-4 shadow-sm">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-foreground">
              {competitor.title}
            </p>
            <p className="text-xs text-muted-foreground">
              {competitor.brand ? `${competitor.brand} • ` : ""}
              {competitor.storeName}
            </p>
          </div>
          {viewButton}
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Price
            </p>
            <p className="font-medium text-foreground">
              {formatMetric(competitor.price, formatCurrency)}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Rating
            </p>
            <p className="font-medium text-foreground">
              {formatMetric(
                competitor.rating,
                (value) => `${value.toFixed(1)} / 5`
              )}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Sold
            </p>
            <p className="font-medium text-foreground">
              {formatSoldCount(competitor.soldCount)}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Similarity
            </p>
            <p className={cn("font-medium", similarityTone)}>
              {formatPercentScore(similarityValue ?? null)}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Stock
            </p>
            <span
              className={cn(
                "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
                stockBadgeStyle
              )}
            >
              {competitor.stockStatus}
            </span>
          </div>
        </div>

        {attributeEntries.length > 0 ? (
          <details className="mt-4 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
            <summary className="cursor-pointer font-semibold text-foreground">
              View matched attributes
            </summary>
            <div className="mt-2 space-y-1">
              {shownAttributes.map(([key, value]) => (
                <p key={key}>
                  <span className="font-medium text-foreground">{key}:</span> {value}
                </p>
              ))}
              {attributeEntries.length > shownAttributes.length ? (
                <p>+{attributeEntries.length - shownAttributes.length} more</p>
              ) : null}
            </div>
          </details>
        ) : null}
      </div>
    )
  }

  return (
    <>
      <tr className="border-b last:border-0">
        <td className="px-4 py-3">
          <div className="font-medium text-foreground">{competitor.title}</div>
          <div className="text-xs text-muted-foreground">
            {competitor.brand ? `${competitor.brand} • ` : ""}
            {competitor.storeName}
          </div>
        </td>
        <td className="px-4 py-3 text-muted-foreground">
          {formatMetric(competitor.price, formatCurrency)}
        </td>
        <td className="px-4 py-3 text-muted-foreground">
          {formatMetric(
            competitor.rating,
            (value) => `${value.toFixed(1)} / 5`
          )}
        </td>
        <td className="px-4 py-3 text-muted-foreground">
          {formatSoldCount(competitor.soldCount)}
        </td>
        <td className="px-4 py-3">
          <span
            className={cn(
              "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
              stockBadgeStyle
            )}
          >
            {competitor.stockStatus}
          </span>
        </td>
        <td className={cn("px-4 py-3 font-medium", similarityTone)}>
          {formatPercentScore(similarityValue ?? null)}
        </td>
        <td className="px-4 py-3 text-muted-foreground">{competitor.storeName}</td>
        <td className="px-4 py-3 text-right">
          <div className="flex items-center justify-end gap-2">
            {viewButton}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setIsExpanded((prev) => !prev)}
            >
              {isExpanded ? "Hide" : "Details"}
            </Button>
          </div>
        </td>
      </tr>
      {isExpanded ? (
        <tr className="bg-muted/20">
          <td colSpan={8} className="px-4 py-3 text-xs text-muted-foreground">
            <div className="grid gap-2 md:grid-cols-2">
              <div>
                <p className="font-semibold text-foreground">Matched attributes</p>
                {attributeEntries.length === 0 ? (
                  <p>No attributes captured yet.</p>
                ) : (
                  <div className="mt-1 space-y-1">
                    {attributeEntries.map(([key, value]) => (
                      <p key={key}>
                        <span className="font-medium text-foreground">{key}:</span>{" "}
                        {value}
                      </p>
                    ))}
                  </div>
                )}
              </div>
              {competitor.description ? (
                <div className="md:col-span-2">
                  <p className="font-semibold text-foreground">Competitor description</p>
                  <p className="mt-1">{competitor.description}</p>
                </div>
              ) : null}
            </div>
          </td>
        </tr>
      ) : null}
    </>
  )
}
