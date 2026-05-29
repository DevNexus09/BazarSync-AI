import { Flame } from "lucide-react"

import { cn } from "@/lib/utils"
import { formatNumber } from "@/utils/formatters"

type UrgencyScoreWidgetProps = {
  score?: number
  isLoading: boolean
}

const scoreTone = (score: number) => {
<<<<<<< HEAD
  if (score >= 80) return "text-rose-300"
  if (score >= 60) return "text-amber-300"
  return "text-emerald-300"
=======
  if (score >= 80) return "text-rose-600"
  if (score >= 60) return "text-amber-600"
  return "text-emerald-600"
>>>>>>> develop
}

export function UrgencyScoreWidget({
  score = 0,
  isLoading,
}: UrgencyScoreWidgetProps) {
  if (isLoading) {
    return (
<<<<<<< HEAD
      <div className="glass-panel p-4">
=======
      <div className="rounded-xl border bg-background p-4 shadow-sm">
>>>>>>> develop
        <div className="h-4 w-28 animate-pulse rounded bg-muted/60" />
        <div className="mt-3 h-16 animate-pulse rounded bg-muted/30" />
      </div>
    )
  }

  return (
<<<<<<< HEAD
    <div className="glass-panel p-4">
=======
    <div className="rounded-xl border bg-background p-4 shadow-sm">
>>>>>>> develop
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
<<<<<<< HEAD
      <div className="mt-3 h-2 rounded-full bg-muted/50">
=======
      <div className="mt-3 h-2 rounded-full bg-muted">
>>>>>>> develop
        <div
          className={cn("h-2 rounded-full", scoreTone(score))}
          style={{ width: `${score}%`, backgroundColor: "currentColor" }}
        />
      </div>
    </div>
  )
}
