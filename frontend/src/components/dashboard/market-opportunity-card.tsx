import { Sparkles } from "lucide-react"

import { cn } from "@/lib/utils"
import type { MarketOpportunity } from "@/types/dashboard"
import { formatCurrency, formatNumber, formatPercent } from "@/utils/formatters"

type MarketOpportunityCardProps = {
  opportunity: MarketOpportunity
}

const urgencyTone = (score: number) => {
  if (score >= 80) return "text-danger bg-rose-500/15"
  if (score >= 60) return "text-warning bg-amber-500/15"
  return "text-success bg-emerald-500/15"
}

export function MarketOpportunityCard({ opportunity }: MarketOpportunityCardProps) {
  const probability =
    opportunity.probability <= 1
      ? opportunity.probability * 100
      : opportunity.probability

  return (
    <div className="rounded-xl border border-border/60 bg-card/70 p-4 shadow-[0_0_0_1px_rgb(var(--primary)/.12)]">
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
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/15 text-primary">
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
