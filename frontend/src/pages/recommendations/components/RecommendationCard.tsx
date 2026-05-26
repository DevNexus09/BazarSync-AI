import { Clock } from "lucide-react"

import { cn } from "@/lib/utils"

import type { RecommendationResponse } from "../types/recommendation"
import { getConfidenceTone } from "../utils/recommendationHelpers"
import { ActionBadge } from "./ActionBadge"

type RecommendationCardProps = {
  recommendation: RecommendationResponse
  productTitle: string
  createdAt?: string
  className?: string
}

export function RecommendationCard({
  recommendation,
  productTitle,
  createdAt,
  className,
}: RecommendationCardProps) {
  return (
    <div className={cn("rounded-xl border bg-background p-5 shadow-sm", className)}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            AI recommendation
          </p>
          <h3 className="mt-2 text-lg font-semibold text-foreground">
            {productTitle}
          </h3>
        </div>
        <ActionBadge action={recommendation.action} />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
        <span
          className={cn(
            "rounded-full border px-2 py-1 text-xs font-semibold uppercase",
            getConfidenceTone(recommendation.confidence)
          )}
        >
          {recommendation.confidence} confidence
        </span>
        {createdAt ? (
          <span className="flex items-center gap-1 text-xs">
            <Clock className="size-3" />
            {new Date(createdAt).toLocaleString()}
          </span>
        ) : null}
      </div>

      <div className="mt-5 rounded-lg border bg-muted/30 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Bangla reasoning
        </p>
        <p
          className="mt-2 text-sm leading-relaxed text-foreground"
          lang="bn"
        >
          {recommendation.reasoningBn}
        </p>
      </div>
    </div>
  )
}
