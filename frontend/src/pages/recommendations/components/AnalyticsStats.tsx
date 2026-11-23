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
    helper: "Observed competitor listings.",
  },
  {
    label: "Price gap",
    value: formatSignedPercent(analytics.priceGapPercent),
    icon: TrendingDown,
    helper: "Calculated from listed prices.",
  },
  {
    label: "Stock risk",
    value: analytics.stockRiskAvailable === false || analytics.stockRiskScore === null ? "Unavailable" : formatScorePercent(analytics.stockRiskScore),
    icon: AlertTriangle,
    helper: "Heuristic inventory signal.",
  },
  {
    label: "Competitors OOS",
    value: formatNullableNumber(analytics.competitorsOos ?? null),
    icon: Activity,
    helper: "Observed competitor listings.",
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
            className="glass-surface relative rounded-[20px] p-4"
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
