import { Sparkles } from "lucide-react"

import { formatCurrency } from "@/utils/formatters"

type RevenueOpportunityCardProps = {
  value: number
  className?: string
}

export function RevenueOpportunityCard({
  value,
  className,
}: RevenueOpportunityCardProps) {
  return (
    <div className={className}>
      <div className="rounded-xl border bg-gradient-to-br from-primary/5 via-background to-emerald-50/60 p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Revenue opportunity
          </p>
          <Sparkles className="size-4 text-emerald-500" />
        </div>
        <div className="mt-3 text-2xl font-semibold text-foreground">
          {formatCurrency(value)}
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          Estimated upside from the recommended pricing action.
        </p>
      </div>
    </div>
  )
}
