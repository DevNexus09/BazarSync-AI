import { Activity, Bell, Bot, Server } from "lucide-react"

import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/common/error-state"
import { ActivitySeverity, type ActivityItem } from "@/types/dashboard"
import { cn } from "@/lib/utils"

type RealtimeActivityFeedProps = {
  items?: ActivityItem[]
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}

const categoryIcons: Record<ActivityItem["category"], typeof Activity> = {
  recommendation: Bot,
  alert: Bell,
  competitor: Activity,
  system: Server,
}

const severityTone: Record<ActivitySeverity, string> = {
<<<<<<< HEAD
  [ActivitySeverity.Info]: "text-emerald-300",
  [ActivitySeverity.Warning]: "text-amber-300",
  [ActivitySeverity.Critical]: "text-rose-300",
=======
  [ActivitySeverity.Info]: "text-emerald-500",
  [ActivitySeverity.Warning]: "text-amber-500",
  [ActivitySeverity.Critical]: "text-rose-500",
>>>>>>> develop
}

export function RealtimeActivityFeed({
  items,
  isLoading,
  isError,
  onRetry,
}: RealtimeActivityFeedProps) {
  if (isLoading) {
    return (
<<<<<<< HEAD
      <div className="glass-panel p-4">
=======
      <div className="rounded-xl border bg-background p-4 shadow-sm">
>>>>>>> develop
        <div className="h-5 w-32 animate-pulse rounded bg-muted/60" />
        <div className="mt-4 space-y-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={`feed-skeleton-${index}`}
              className="h-10 rounded-lg bg-muted/30"
            />
          ))}
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <ErrorState
        title="Activity feed unavailable"
        message="Realtime activity could not be loaded."
        action={
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        }
      />
    )
  }

  const feed = items ?? []

  return (
<<<<<<< HEAD
    <div className="glass-panel p-4">
=======
    <div className="rounded-xl border bg-background p-4 shadow-sm">
>>>>>>> develop
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">
          Realtime activity
        </h3>
        <span className="text-xs text-muted-foreground">
          {feed.length} signals
        </span>
      </div>
      {feed.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed bg-muted/30 p-4 text-xs text-muted-foreground">
          Waiting for live events from the BazarSync-AI engine.
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          {feed.map((item) => {
            const Icon = categoryIcons[item.category]
            return (
              <div
                key={item.id}
<<<<<<< HEAD
                className="flex items-start gap-3 rounded-lg border border-border/60 bg-card/60 p-3"
=======
                className="flex items-start gap-3 rounded-lg border bg-muted/10 p-3"
>>>>>>> develop
              >
                <Icon
                  className={cn(
                    "mt-0.5 size-4",
                    severityTone[item.severity]
                  )}
                />
                <div className="flex-1">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-semibold text-foreground">
                      {item.title}
                    </p>
                    <span className="text-[11px] text-muted-foreground">
                      {new Date(item.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {item.description}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}