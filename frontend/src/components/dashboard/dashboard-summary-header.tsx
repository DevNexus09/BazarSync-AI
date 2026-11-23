import type { ReactNode } from "react"
import { RefreshCcw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { LiveStatusIndicator } from "@/components/dashboard/live-status-indicator"
import { cn } from "@/lib/utils"
import {
  KpiTrend,
  type DashboardSummary,
  type RealtimeStatus,
} from "@/types/dashboard"
import { formatDateTime, formatNumber } from "@/utils/formatters"

type DashboardSummaryHeaderProps = {
  summary?: DashboardSummary
  isLoading: boolean
  isRefreshing: boolean
  realtimeStatus?: RealtimeStatus
  onRefresh: () => void
  aside?: ReactNode
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
  realtimeStatus,
  onRefresh,
  aside,
}: DashboardSummaryHeaderProps) {
  if (isLoading && !summary) {
    return (
      <div className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-2">
            <div className="h-6 w-48 animate-pulse rounded bg-muted/70" />
            <div className="h-4 w-72 animate-pulse rounded bg-muted/50" />
          </div>
          <div className="h-10 w-40 animate-pulse rounded-lg bg-muted/50" />
        </div>
        <div className="h-24 animate-pulse rounded-xl bg-muted/30" />
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
              delta: "Open now",
              trend: KpiTrend.Flat,
            },
            {
              label: "Monitored products",
              value: formatNumber(summary.liveCompetitors),
              delta: "Tracked against competitors",
              trend: KpiTrend.Flat,
            },
            {
              label: "AI recommendations",
              value: formatNumber(summary.aiRecommendations),
              delta: "In the last hour",
              trend: KpiTrend.Flat,
            },
            {
              label: "Revenue opportunities",
              value: formatNumber(summary.revenueOpportunities),
              delta: "Open opportunities",
              trend: KpiTrend.Flat,
            },
          ]
        : []

  return (
    <section className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="heading-font text-2xl font-semibold text-foreground">
            AI Operations Center
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            What changed in your market and what to do next.
            {summary?.lastSyncedAt
              ? ` Updated ${formatDateTime(summary.lastSyncedAt)}.`
              : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {realtimeStatus ? (
            <LiveStatusIndicator status={realtimeStatus} />
          ) : null}
          <Button variant="outline" size="sm" onClick={onRefresh}>
            <RefreshCcw
              className={cn("size-4", isRefreshing ? "animate-spin" : "")}
            />
            {isRefreshing ? "Syncing" : "Sync now"}
          </Button>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-12">
      <dl className="glass-panel grid grid-cols-2 divide-border/50 lg:grid-cols-4 lg:divide-x xl:col-span-9">
        {metrics.map((metric) => (
          <div key={metric.label} className="px-5 py-4">
            <dt className="text-xs text-muted-foreground">{metric.label}</dt>
            <dd className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
              {metric.value}
            </dd>
            <dd
              className={cn("mt-0.5 text-xs", trendStyles[metric.trend])}
            >
              {metric.delta}
            </dd>
          </div>
        ))}
      </dl>
      {aside ? <div className="xl:col-span-3">{aside}</div> : null}
      </div>

    </section>
  )
}
