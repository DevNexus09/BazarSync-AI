import { AlertTriangle, CheckCircle2, Clock } from "lucide-react"

import type { TelegramConnectionState } from "@/types/telegram"
import { cn } from "@/lib/utils"

const statusConfig: Record<
  TelegramConnectionState,
  { label: string; tone: string; Icon: typeof CheckCircle2 }
> = {
  not_connected: {
    label: "Not connected",
    tone: "bg-muted/60 text-muted-foreground",
    Icon: Clock,
  },
  connecting: {
    label: "Connecting",
    tone: "bg-amber-500/15 text-warning",
    Icon: Clock,
  },
  connected: {
    label: "Connected",
    tone: "bg-emerald-500/15 text-success",
    Icon: CheckCircle2,
  },
  error: {
    label: "Error",
    tone: "bg-rose-500/15 text-danger",
    Icon: AlertTriangle,
  },
}

type TelegramStatusBadgeProps = {
  state: TelegramConnectionState
}

export function TelegramStatusBadge({ state }: TelegramStatusBadgeProps) {
  const { label, tone, Icon } = statusConfig[state]
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold",
        tone
      )}
    >
      <Icon className="size-3.5" />
      {label}
    </span>
  )
}
