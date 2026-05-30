import { CheckCircle2, Clock } from "lucide-react"

import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/common/error-state"
import { cn } from "@/lib/utils"
import { AlertStatus, type Alert } from "@/types/alert"

type AlertHistoryPanelProps = {
  alerts?: Alert[]
  isLoading: boolean
  isError: boolean
  onRetry: () => void
  onResolve: (alertId: string) => void
  resolvingId?: string | null
}

const statusStyles: Record<AlertStatus, string> = {
  [AlertStatus.New]: "bg-rose-500/15 text-rose-300",
  [AlertStatus.Acknowledged]: "bg-amber-500/15 text-amber-300",
  [AlertStatus.Resolved]: "bg-emerald-500/15 text-emerald-300",
}

export function AlertHistoryPanel({
  alerts,
  isLoading,
  isError,
  onRetry,
  onResolve,
  resolvingId,
}: AlertHistoryPanelProps) {
  if (isLoading) {
    return (
      <div className="glass-panel p-4">
        <div className="h-5 w-32 animate-pulse rounded bg-muted/60" />
        <div className="mt-4 space-y-2">
          {Array.from({ length: 5 }).map((_, index) => (
            <div
              key={`alert-history-skeleton-${index}`}
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
        title="Alert history unavailable"
        message="We couldn't load the alert history yet."
        action={
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        }
      />
    )
  }

  const history = alerts ?? []

  return (
    <div className="glass-panel p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">
          Telegram alert feed
        </h3>
        <span className="text-xs text-muted-foreground">
          {history.length} total
        </span>
      </div>
      {history.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed bg-muted/30 p-4 text-xs text-muted-foreground">
          Alerts will appear here once market risks are detected.
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          {history.map((alert) => (
            <div
              key={alert.id}
              className="rounded-lg border border-border/60 bg-card/60 p-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="text-xs font-semibold text-foreground">
                    {alert.title}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {alert.message}
                  </p>
                </div>
                <span
                  className={cn(
                    "rounded-full px-2.5 py-1 text-[11px] font-semibold",
                    statusStyles[alert.status]
                  )}
                >
                  {alert.status.replace("_", " ")}
                </span>
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <Clock className="size-3.5" />
                  {new Date(alert.createdAt).toLocaleString()}
                </span>
                {alert.status !== AlertStatus.Resolved ? (
                  <Button
                    size="xs"
                    variant="outline"
                    onClick={() => onResolve(alert.id)}
                    disabled={resolvingId === alert.id}
                  >
                    <CheckCircle2 className="size-3.5" />
                    {resolvingId === alert.id ? "Resolving" : "Resolve"}
                  </Button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}