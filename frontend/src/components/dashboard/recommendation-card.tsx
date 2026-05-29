import { CheckCircle2, Sparkles } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  RecommendationAction,
  RecommendationPriority,
  RecommendationStatus,
  type Recommendation,
} from "@/types/recommendation"
import { formatPercent } from "@/utils/formatters"

type RecommendationCardProps = {
  recommendation: Recommendation
}

const priorityStyles: Record<RecommendationPriority, string> = {
<<<<<<< HEAD
  [RecommendationPriority.Low]: "bg-muted/60 text-muted-foreground",
  [RecommendationPriority.Medium]: "bg-amber-500/15 text-amber-300",
  [RecommendationPriority.High]: "bg-rose-500/15 text-rose-300",
  [RecommendationPriority.Critical]: "bg-rose-500/25 text-rose-200",
}

const statusStyles: Record<RecommendationStatus, string> = {
  [RecommendationStatus.New]: "bg-emerald-500/15 text-emerald-300",
  [RecommendationStatus.Reviewed]: "bg-sky-500/15 text-sky-300",
  [RecommendationStatus.Implemented]: "bg-indigo-500/15 text-indigo-300",
  [RecommendationStatus.Dismissed]: "bg-muted/60 text-muted-foreground",
=======
  [RecommendationPriority.Low]: "bg-muted text-muted-foreground",
  [RecommendationPriority.Medium]: "bg-amber-100 text-amber-700",
  [RecommendationPriority.High]: "bg-rose-100 text-rose-700",
  [RecommendationPriority.Critical]: "bg-rose-200 text-rose-800",
}

const statusStyles: Record<RecommendationStatus, string> = {
  [RecommendationStatus.New]: "bg-emerald-100 text-emerald-700",
  [RecommendationStatus.Reviewed]: "bg-blue-100 text-blue-700",
  [RecommendationStatus.Implemented]: "bg-indigo-100 text-indigo-700",
  [RecommendationStatus.Dismissed]: "bg-muted text-muted-foreground",
>>>>>>> develop
}

const actionLabels: Record<RecommendationAction, string> = {
  [RecommendationAction.RaisePrice]: "Raise price",
  [RecommendationAction.MatchPrice]: "Match competitor",
  [RecommendationAction.Undercut]: "Undercut",
  [RecommendationAction.Bundle]: "Bundle offer",
  [RecommendationAction.Restock]: "Restock",
  [RecommendationAction.Hold]: "Hold price",
}

export function RecommendationCard({ recommendation }: RecommendationCardProps) {
  const confidence =
    recommendation.confidence <= 1
      ? recommendation.confidence * 100
      : recommendation.confidence
  const expectedLift =
    recommendation.expectedLift <= 1
      ? recommendation.expectedLift * 100
      : recommendation.expectedLift

  return (
<<<<<<< HEAD
    <div className="rounded-xl border border-border/60 bg-card/70 p-4 shadow-[0_0_0_1px_rgba(139,92,246,0.15)]">
=======
    <div className="rounded-xl border bg-background p-4 shadow-sm">
>>>>>>> develop
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs text-muted-foreground">
            {recommendation.product}
          </p>
          <h4 className="text-sm font-semibold text-foreground">
            {recommendation.title}
          </h4>
          <p className="mt-1 text-xs text-muted-foreground">
            {recommendation.summary}
          </p>
        </div>
<<<<<<< HEAD
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/15 text-primary">
=======
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 text-primary">
>>>>>>> develop
          <Sparkles className="size-4" />
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
        <span
          className={cn(
            "rounded-full px-2.5 py-1 font-semibold",
            priorityStyles[recommendation.priority]
          )}
        >
          {recommendation.priority.toUpperCase()}
        </span>
        <span
          className={cn(
            "rounded-full px-2.5 py-1 font-semibold",
            statusStyles[recommendation.status]
          )}
        >
          {recommendation.status.replace("_", " ")}
        </span>
      </div>
      <div className="mt-4 grid gap-2 text-xs text-muted-foreground">
        <div className="flex items-center justify-between">
          <span>Recommended action</span>
          <span className="font-semibold text-foreground">
            {actionLabels[recommendation.action]}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>Confidence</span>
          <span className="font-semibold text-foreground">
            {formatPercent(confidence)}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>Expected lift</span>
          <span className="font-semibold text-foreground">
            {formatPercent(expectedLift)}
          </span>
        </div>
      </div>
      <div className="mt-4 inline-flex items-center gap-1 text-xs text-muted-foreground">
        <CheckCircle2 className="size-3.5" />
        Updated {new Date(recommendation.createdAt).toLocaleString()}
      </div>
    </div>
  )
}