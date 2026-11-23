import { Flame } from "lucide-react"

import { cn } from "@/lib/utils"
import { formatNumber } from "@/utils/formatters"

type UrgencyScoreWidgetProps = {
  score?: number
  isLoading: boolean
}

const scoreTone = (score: number) => {
  if (score >= 80) return "text-danger"
  if (score >= 60) return "text-warning"
  return "text-success"
}

export function UrgencyScoreWidget({
  score = 0,
  isLoading,
}: UrgencyScoreWidgetProps) {
  if (isLoading) {
    return (
      <div className="glass-panel p-4">
        <div className="h-4 w-28 animate-pulse rounded bg-muted/60" />
        <div className="mt-3 h-16 animate-pulse rounded bg-muted/30" />
      </div>
    )
  }

  return (
    <div className="glass-panel p-4">
      <div className="flex items-center gap-2">
        <Flame className={cn("size-4", scoreTone(score))} />
        <h3 className="text-sm font-semibold text-foreground">
          Urgency score
        </h3>
      </div>
      <div className="mt-4 flex items-end justify-between">
        <div className={cn("text-3xl font-semibold", scoreTone(score))}>
          {formatNumber(score)}
        </div>
        <div className="text-xs text-muted-foreground">
          {score >= 80
            ? "Critical actions required"
            : score >= 60
              ? "Elevated competitive risk"
              : "Stable competitive posture"}
        </div>
      </div>
      <div className="mt-3 h-2 rounded-full bg-muted/50">
        <div
          className={cn("h-2 rounded-full", scoreTone(score))}
          style={{ width: `${score}%`, backgroundColor: "currentColor" }}
        />
      </div>
    </div>
  )
}
