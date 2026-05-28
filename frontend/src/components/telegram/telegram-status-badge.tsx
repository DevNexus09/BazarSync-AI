import { AlertTriangle, CheckCircle2, Clock } from "lucide-react"

import type { TelegramConnectionState } from "@/types/telegram"
import { cn } from "@/lib/utils"

const statusConfig: Record<
  TelegramConnectionState,
  { label: string; tone: string; Icon: typeof CheckCircle2 }
> = {
  not_connected: {
    label: "Not connected",
    tone: "bg-muted text-muted-foreground",
    Icon: Clock,
  },
  connecting: {
    label: "Connecting",
    tone: "bg-amber-100 text-amber-700",
    Icon: Clock,
  },
  connected: {
    label: "Connected",
    tone: "bg-emerald-100 text-emerald-700",
    Icon: CheckCircle2,
  },
  error: {
    label: "Error",
    tone: "bg-rose-100 text-rose-700",
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
