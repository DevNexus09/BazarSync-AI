import { Sparkles } from "lucide-react"

import { formatOptionalCurrency } from "@/utils/formatters"

type RevenueOpportunityCardProps = {
  value: number | null
  className?: string
}

export function RevenueOpportunityCard({
  value,
  className,
}: RevenueOpportunityCardProps) {
  return (
    <div className={className}>
      <div className="glass-surface relative rounded-[20px] p-4">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Revenue opportunity
          </p>
          <Sparkles className="size-4 text-success" />
        </div>
        <div className="mt-3 text-2xl font-semibold text-foreground">
          {formatOptionalCurrency(value)}
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          Legacy heuristic estimate.
        </p>
      </div>
    </div>
  )
}
