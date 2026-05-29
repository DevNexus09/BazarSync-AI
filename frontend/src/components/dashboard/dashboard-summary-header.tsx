import { RefreshCcw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import {
  KpiTrend,
  type DashboardSummary,
} from "@/types/dashboard"
import { formatNumber } from "@/utils/formatters"

type DashboardSummaryHeaderProps = {
  summary?: DashboardSummary
  isLoading: boolean
  isRefreshing: boolean
  onRefresh: () => void
}

const trendStyles: Record<KpiTrend, string> = {
  [KpiTrend.Up]: "text-emerald-600",
  [KpiTrend.Down]: "text-rose-600",
  [KpiTrend.Flat]: "text-muted-foreground",
}

export function DashboardSummaryHeader({
  summary,
  isLoading,
  isRefreshing,
  onRefresh,
}: DashboardSummaryHeaderProps) {
  if (isLoading && !summary) {
    return (
      <div className="glass-panel p-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-2">
            <div className="h-6 w-48 animate-pulse rounded bg-muted/70" />
            <div className="h-4 w-72 animate-pulse rounded bg-muted/50" />
          </div>
          <div className="h-10 w-40 animate-pulse rounded-lg bg-muted/50" />
        </div>
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={`summary-skeleton-${index}`}
              className="h-20 rounded-xl border bg-muted/30"
            />
          ))}
        </div>
      </div>
    )
  }

  const metrics =
    summary?.kpis.length
      ? summary.kpis
      : summary
        ? [
            {
              label: "Active alerts",
              value: formatNumber(summary.activeAlerts),
              delta: "Realtime",
              trend: KpiTrend.Up,
            },
            {
              label: "Live competitors",
              value: formatNumber(summary.liveCompetitors),
              delta: "Tracking",
              trend: KpiTrend.Flat,
            },
            {
              label: "AI recommendations",
              value: formatNumber(summary.aiRecommendations),
              delta: "Today",
              trend: KpiTrend.Up,
            },
            {
              label: "Revenue opportunities",
              value: formatNumber(summary.revenueOpportunities),
              delta: "This week",
              trend: KpiTrend.Up,
            },
          ]
        : []

  return (
    <section className="glass-panel p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
            AI Operations Center
          </p>
          <h1 className="heading-font text-2xl font-semibold text-foreground">
            Realtime marketplace intelligence
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Live pricing, urgency, and recommendation signals for BazarSync AI
            sellers.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" onClick={onRefresh}>
            <RefreshCcw
              className={cn("size-4", isRefreshing ? "animate-spin" : "")}
            />
            {isRefreshing ? "Syncing" : "Sync now"}
          </Button>
        </div>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {metrics.map((metric) => (
          <div
            key={metric.label}
            className="rounded-xl border border-border/60 bg-card/60 p-4 transition hover:-translate-y-0.5 hover:shadow-[0_0_18px_rgba(59,130,246,0.2)]"
          >
            <p className="text-xs text-muted-foreground">{metric.label}</p>
            <div className="mt-2 text-2xl font-semibold text-foreground">
              {metric.value}
            </div>
            <p className={cn("mt-1 text-xs font-semibold", trendStyles[metric.trend])}>
              {metric.delta}
            </p>
          </div>
        ))}
      </div>

      {summary?.insights?.length ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {summary.insights.slice(0, 2).map((insight) => (
            <div
              key={insight.id}
              className="rounded-xl border border-dashed bg-muted/30 p-4"
            >
              <div className="text-sm font-semibold text-foreground">
                {insight.title}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {insight.summary}
              </p>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}