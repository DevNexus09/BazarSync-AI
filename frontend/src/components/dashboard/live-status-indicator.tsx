import { Activity, RefreshCcw, WifiOff } from "lucide-react"

import { cn } from "@/lib/utils"
import type { RealtimeStatus } from "@/types/dashboard"

type LiveStatusIndicatorProps = {
  status: RealtimeStatus
  className?: string
}

const formatRelativeTime = (value: string | null) => {
  if (!value) {
    return "Waiting for events"
  }
  const now = new Date()
  const date = new Date(value)
  const diffSeconds = Math.round((date.getTime() - now.getTime()) / 1000)
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" })

  if (Math.abs(diffSeconds) < 60) {
    return rtf.format(diffSeconds, "second")
  }
  const diffMinutes = Math.round(diffSeconds / 60)
  if (Math.abs(diffMinutes) < 60) {
    return rtf.format(diffMinutes, "minute")
  }
  const diffHours = Math.round(diffMinutes / 60)
  return rtf.format(diffHours, "hour")
}

export function LiveStatusIndicator({ status, className }: LiveStatusIndicatorProps) {
  const isLive = status.connected
  const isReconnecting = status.reconnecting
  const label = isLive
    ? "Live sync"
    : isReconnecting
      ? "Reconnecting"
      : "Offline"
  const Icon = isLive ? Activity : isReconnecting ? RefreshCcw : WifiOff

  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-xl border border-border/60 bg-card/60 px-3 py-2 shadow-[0_0_0_1px_rgb(var(--primary)/.15)]",
        className
      )}
      role="status"
      aria-live="polite"
    >
      <span
        className={cn(
          "inline-flex size-2 rounded-full",
          isLive
            ? "bg-success shadow-[0_0_0_4px_rgb(var(--success)/.15)]"
            : isReconnecting
              ? "bg-warning shadow-[0_0_0_4px_rgb(var(--warning)/.15)]"
              : "bg-danger shadow-[0_0_0_4px_rgb(var(--danger)/.15)]"
        )}
        aria-hidden="true"
      />
      <div className="flex flex-col">
        <span className="text-xs font-semibold text-foreground">{label}</span>
        <span className="text-[11px] text-muted-foreground">
          {formatRelativeTime(status.lastEventAt)}
        </span>
      </div>
      <div className="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground">
        <Icon className="size-3.5" />
        <span className="capitalize">{status.transport ?? "websocket"}</span>
      </div>
    </div>
  )
}
