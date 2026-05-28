import { Sparkles } from "lucide-react"

import { cn } from "@/lib/utils"
import type { MarketOpportunity } from "@/types/dashboard"
import { formatCurrency, formatNumber, formatPercent } from "@/utils/formatters"

type MarketOpportunityCardProps = {
  opportunity: MarketOpportunity
}

const urgencyTone = (score: number) => {
  if (score >= 80) return "text-rose-600 bg-rose-50"
  if (score >= 60) return "text-amber-600 bg-amber-50"
  return "text-emerald-600 bg-emerald-50"
}

export function MarketOpportunityCard({ opportunity }: MarketOpportunityCardProps) {
  const probability =
    opportunity.probability <= 1
      ? opportunity.probability * 100
      : opportunity.probability

  return (
    <div className="rounded-xl border bg-background p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs text-muted-foreground">
            {opportunity.category.toUpperCase()}
          </p>
          <h4 className="text-sm font-semibold text-foreground">
            {opportunity.title}
          </h4>
          <p className="mt-1 text-xs text-muted-foreground">
            {opportunity.description}
          </p>
        </div>
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Sparkles className="size-4" />
        </div>
      </div>
      <div className="mt-4 grid gap-2 text-xs text-muted-foreground">
        <div className="flex items-center justify-between">
          <span>Potential revenue</span>
          <span className="font-semibold text-foreground">
            {formatCurrency(opportunity.potentialRevenue)}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>Win probability</span>
          <span className="font-semibold text-foreground">
            {formatPercent(probability)}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>Time window</span>
          <span className="font-semibold text-foreground">
            {opportunity.timeWindow}
          </span>
        </div>
      </div>
      <div
        className={cn(
          "mt-4 inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold",
          urgencyTone(opportunity.urgencyScore)
        )}
      >
        Urgency {formatNumber(opportunity.urgencyScore)}
      </div>
    </div>
  )
}