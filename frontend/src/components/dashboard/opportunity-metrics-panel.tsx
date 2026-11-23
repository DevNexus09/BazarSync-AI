import { ErrorState } from "@/components/common/error-state"
import { EmptyHint } from "@/components/dashboard/empty-hint"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { KpiTrend, type OpportunityMetric } from "@/types/dashboard"

type OpportunityMetricsPanelProps = {
  metrics?: OpportunityMetric[]
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}

const trendStyles: Record<KpiTrend, string> = {
  [KpiTrend.Up]: "text-success",
  [KpiTrend.Down]: "text-danger",
  [KpiTrend.Flat]: "text-muted-foreground",
}

export function OpportunityMetricsPanel({
  metrics,
  isLoading,
  isError,
  onRetry,
}: OpportunityMetricsPanelProps) {
  if (isLoading) {
    return (
      <div className="glass-panel p-4">
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

  if (isError) {
    return (
      <ErrorState
        title="Opportunity metrics unavailable"
        message="Opportunity metrics could not be loaded."
        action={
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        }
      />
    )
  }

  const items = metrics ?? []

  return (
    <div className="glass-panel p-4">
      <h3 className="text-sm font-semibold text-foreground">
        Opportunity metrics
      </h3>
      {items.length === 0 ? (
        <EmptyHint
          message="No recommendations yet. Generate one to see revenue, confidence and opportunity signals."
          actionLabel="Generate recommendations"
          to="/app/recommendations"
        />
      ) : (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {items.map((metric) => (
            <div
              key={metric.id}
              className="rounded-lg border border-border/60 bg-card/60 p-3"
            >
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
