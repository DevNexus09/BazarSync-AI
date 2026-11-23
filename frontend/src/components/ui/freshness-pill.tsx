import { Clock, RefreshCcw } from "lucide-react"

import { ui } from "@/lib/ui-i18n"
import { cn } from "@/lib/utils"
import { formatRelativeTime, hoursSince } from "@/utils/formatters"

/** "Updated 2 hours ago", or a warning with a refresh button once older than staleAfterHours. */
export function FreshnessPill({
  updatedAt,
  staleAfterHours = 24,
  onRefresh,
  refreshing = false,
  now,
}: {
  updatedAt: string | null | undefined
  staleAfterHours?: number
  onRefresh?: () => void
  refreshing?: boolean
  now?: Date
}) {
  const age = hoursSince(updatedAt, now)
  const stale = age == null || age > staleAfterHours
  const text =
    age == null ? ui("neverUpdated") : ui("updated", { time: formatRelativeTime(updatedAt, now) ?? "" })
  return (
    <span className="inline-flex items-center gap-2 text-xs">
      <span
        data-stale={stale}
        className={cn(
          "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
          stale ? "border-warning/40 bg-warning/10 text-warning" : "border-border bg-muted/40 text-muted-foreground",
        )}
      >
        <Clock aria-hidden className="size-3.5" />
        {stale && age != null ? `${ui("stale")} · ${text}` : text}
      </span>
      {onRefresh ? (
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium text-primary hover:underline disabled:opacity-50"
        >
          <RefreshCcw aria-hidden className={cn("size-3.5", refreshing && "animate-spin")} />
          {ui("refresh")}
        </button>
      ) : null}
    </span>
  )
}
