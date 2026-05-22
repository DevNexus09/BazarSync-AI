import type { ComponentType } from "react"
import { Activity, AlertTriangle, ChartLine, TrendingDown } from "lucide-react"

import { cn } from "@/lib/utils"

import type { RecommendationAnalytics } from "../types/recommendation"
import {
  formatNullableCurrency,
  formatNullableNumber,
  formatScorePercent,
  formatSignedPercent,
} from "../utils/recommendationHelpers"

type AnalyticsStatsProps = {
  analytics: RecommendationAnalytics
  className?: string
}

const stats = (
  analytics: RecommendationAnalytics
): Array<{
  label: string
  value: string
  icon: ComponentType<{ className?: string }>
  helper: string
}> => [
  {
    label: "Competitor median price",
    value: formatNullableCurrency(analytics.competitorMedianPrice),
    icon: ChartLine,
    helper: "Market midpoint pricing.",
  },
  {
    label: "Price gap",
    value: formatSignedPercent(analytics.priceGapPercent),
    icon: TrendingDown,
    helper: "Seller vs median gap.",
  },
  {
    label: "Stock risk",
    value: formatScorePercent(analytics.stockRiskScore),
    icon: AlertTriangle,
    helper: "Inventory urgency signal.",
  },
  {
    label: "Competitors OOS",
    value: formatNullableNumber(analytics.competitorsOos ?? null),
    icon: Activity,
    helper: "Out-of-stock rivals.",
  },
]

export function AnalyticsStats({ analytics, className }: AnalyticsStatsProps) {
  return (
    <div className={cn("grid gap-3 sm:grid-cols-2", className)}>
      {stats(analytics).map((stat) => {
        const Icon = stat.icon
        return (
          <div
            key={stat.label}
            className="rounded-xl border bg-background p-4 shadow-sm"
          >
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {stat.label}
              </p>
              <Icon className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-2 text-lg font-semibold text-foreground">
              {stat.value}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{stat.helper}</p>
          </div>
        )
      })}
    </div>
  )
}
