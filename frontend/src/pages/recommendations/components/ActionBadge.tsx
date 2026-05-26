import type { ComponentType } from "react"
import { ArrowDownRight, ArrowUpRight, PauseCircle, ShoppingCart } from "lucide-react"

import { cn } from "@/lib/utils"

import type { RecommendationAction } from "../types/recommendation"
import { getActionMeta } from "../utils/recommendationHelpers"

const iconMap = {
  LOWER: ArrowDownRight,
  RAISE: ArrowUpRight,
  HOLD: PauseCircle,
  REORDER: ShoppingCart,
} satisfies Record<RecommendationAction, ComponentType<{ className?: string }>>

type ActionBadgeProps = {
  action: RecommendationAction
  className?: string
}

export function ActionBadge({ action, className }: ActionBadgeProps) {
  const meta = getActionMeta(action)
  const Icon = iconMap[action]

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wide",
        meta.tone,
        className
      )}
    >
      <Icon className="size-4" />
      {meta.label}
    </span>
  )
}
