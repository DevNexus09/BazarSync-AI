import { cn } from "@/lib/utils"
import { KpiTrend, type OpportunityMetric } from "@/types/dashboard"

type OpportunityMetricsPanelProps = {
  metrics?: OpportunityMetric[]
  isLoading: boolean
}

const trendStyles: Record<KpiTrend, string> = {
<<<<<<< HEAD
  [KpiTrend.Up]: "text-emerald-300",
  [KpiTrend.Down]: "text-rose-300",
=======
  [KpiTrend.Up]: "text-emerald-600",
  [KpiTrend.Down]: "text-rose-600",
>>>>>>> develop
  [KpiTrend.Flat]: "text-muted-foreground",
}

export function OpportunityMetricsPanel({
  metrics,
  isLoading,
}: OpportunityMetricsPanelProps) {
  if (isLoading) {
    return (
<<<<<<< HEAD
      <div className="glass-panel p-4">
=======
      <div className="rounded-xl border bg-background p-4 shadow-sm">
>>>>>>> develop
        <div className="h-4 w-28 animate-pulse rounded bg-muted/60" />
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={`opportunity-metric-skeleton-${index}`}
              className="h-16 rounded-lg bg-muted/30"
            />
          ))}
        </div>
      </div>
    )
  }

  const items = metrics ?? []

  return (
<<<<<<< HEAD
    <div className="glass-panel p-4">
=======
    <div className="rounded-xl border bg-background p-4 shadow-sm">
>>>>>>> develop
      <h3 className="text-sm font-semibold text-foreground">
        Opportunity metrics
      </h3>
      {items.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed bg-muted/30 p-4 text-xs text-muted-foreground">
          Opportunity metrics will appear when AI signals are available.
        </div>
      ) : (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {items.map((metric) => (
<<<<<<< HEAD
            <div
              key={metric.id}
              className="rounded-lg border border-border/60 bg-card/60 p-3"
            >
=======
            <div key={metric.id} className="rounded-lg border bg-muted/20 p-3">
>>>>>>> develop
              <p className="text-xs text-muted-foreground">{metric.label}</p>
              <p className="mt-2 text-lg font-semibold text-foreground">
                {metric.value}
              </p>
              <p
                className={cn(
                  "mt-1 text-xs font-semibold",
                  trendStyles[metric.trend]
                )}
              >
                {metric.delta}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
