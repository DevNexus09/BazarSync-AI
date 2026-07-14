import { ErrorState } from "@/components/common/error-state"
import { Button } from "@/components/ui/button"
import type { Competitor } from "@/types/competitor"
import { cn } from "@/lib/utils"
import { formatCurrency } from "@/utils/formatters"

type CompetitorHeatmapProps = {
  competitors?: Competitor[]
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}

const getHeatTone = (gap: number) => {
  if (gap <= -200) {
    return "bg-rose-500/20 text-rose-200"
  }
  if (gap <= -50) {
    return "bg-amber-500/20 text-amber-200"
  }
  if (gap >= 200) {
    return "bg-emerald-500/20 text-emerald-200"
  }
  return "bg-muted/60 text-muted-foreground"
}

export function CompetitorHeatmap({
  competitors,
  isLoading,
  isError,
  onRetry,
}: CompetitorHeatmapProps) {
  if (isLoading) {
    return (
      <div className="glass-panel p-5">
        <div className="h-5 w-40 animate-pulse rounded bg-muted/60" />
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {Array.from({ length: 6 }).map((_, index) => (
            <div
              key={`heatmap-skeleton-${index}`}
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
        title="Heatmap unavailable"
        message="We couldn't load competitor heatmap data."
        action={
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        }
      />
    )
  }

  const items = (competitors ?? []).slice(0, 6)

  return (
    <div className="glass-panel p-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            Competitor price heatmap
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Visualize price gaps and urgency across monitored SKUs.
          </p>
        </div>
        <span className="text-xs text-muted-foreground">
          {competitors?.length ?? 0} tracked
        </span>
      </div>
      {items.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed border-border/60 bg-muted/30 p-4 text-xs text-muted-foreground">
          Competitor signals will appear as monitoring begins.
        </div>
      ) : (
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {items.map((item) => (
            <div
              key={item.id}
              className={cn(
                "rounded-xl border border-border/60 px-3 py-3 text-xs",
                getHeatTone(item.priceGap)
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-[11px] uppercase text-muted-foreground">
                  {item.competitor}
                </span>
                <span className="font-semibold text-foreground">
                  {formatCurrency(item.competitorPrice)}
                </span>
              </div>
              <p className="mt-2 text-sm font-semibold text-foreground">
                {item.product}
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Gap {formatCurrency(item.priceGap)} • Urgency {item.urgencyScore}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
