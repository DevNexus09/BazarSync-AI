import { AlertTriangle, CheckCircle2, Clock } from "lucide-react"

import type { TelegramConnectionState } from "@/types/telegram"
import { cn } from "@/lib/utils"

const statusConfig: Record<
  TelegramConnectionState,
  { label: string; tone: string; Icon: typeof CheckCircle2 }
> = {
  not_connected: {
    label: "Not connected",
<<<<<<< HEAD
    tone: "bg-muted/60 text-muted-foreground",
=======
    tone: "bg-muted text-muted-foreground",
>>>>>>> develop
    Icon: Clock,
  },
  connecting: {
    label: "Connecting",
<<<<<<< HEAD
    tone: "bg-amber-500/15 text-amber-300",
=======
    tone: "bg-amber-100 text-amber-700",
>>>>>>> develop
    Icon: Clock,
  },
  connected: {
    label: "Connected",
<<<<<<< HEAD
    tone: "bg-emerald-500/15 text-emerald-300",
=======
    tone: "bg-emerald-100 text-emerald-700",
>>>>>>> develop
    Icon: CheckCircle2,
  },
  error: {
    label: "Error",
<<<<<<< HEAD
    tone: "bg-rose-500/15 text-rose-300",
=======
    tone: "bg-rose-100 text-rose-700",
>>>>>>> develop
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
