import { Clock } from "lucide-react"

import { formatDateTime } from "@/utils/formatters"
import { cn } from "@/lib/utils"

import type { DashboardEvidence } from "../types/dashboardEvidence"
import type { RecommendationResponse } from "../types/recommendation"
import { getConfidenceTone } from "../utils/recommendationHelpers"
import { ActionBadge } from "./ActionBadge"
import { PrimaryEvidence } from "./RecommendationEvidence"

type RecommendationCardProps = {
  recommendation: RecommendationResponse
  productTitle: string
  createdAt?: string
  className?: string
  evidence?: DashboardEvidence
}

export function RecommendationCard({
  recommendation,
  productTitle,
  createdAt,
  className,
  evidence,
}: RecommendationCardProps) {
  return (
    <div className={cn("min-w-0 rounded-xl border bg-background p-5 shadow-sm", className)}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            AI recommendation
          </p>
          <h3 className="mt-2 break-words text-lg font-semibold text-foreground">
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
            {formatDateTime(createdAt)}
          </span>
        ) : null}
      </div>

      {evidence ? (
        <PrimaryEvidence evidence={evidence} lowConfidence={recommendation.confidence === "LOW"} />
      ) : null}

      <div className="mt-5 rounded-lg border bg-muted/30 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Bangla reasoning
        </p>
        <p
          className="mt-2 break-words text-sm leading-relaxed text-foreground"
          lang="bn"
        >
          {recommendation.reasoningBn}
        </p>
      </div>
    </div>
  )
}
