import { FileWarning, Inbox, type LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { ui } from "@/lib/ui-i18n"
import { cn } from "@/lib/utils"

export function EmptyState({
  title,
  message,
  action,
  icon: Icon = Inbox,
}: {
  title: string
  message?: string
  action?: ReactNode
  icon?: LucideIcon
}) {
  return (
    <div className="flex w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border/60 bg-card/60 p-6 text-center">
      <Icon aria-hidden className="size-6 text-muted-foreground" />
      <div className="text-sm font-semibold text-foreground">{title}</div>
      {message ? <div className="text-sm text-muted-foreground">{message}</div> : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  )
}

/** Why a value is unavailable, plus how to fix it. Blocking reasons are shown as warnings. */
export function MissingData({
  title,
  reason,
  nextAction,
  blocking = false,
  action,
}: {
  title: string
  reason: string
  nextAction?: string | null
  blocking?: boolean
  action?: ReactNode
}) {
  return (
    <div
      className={cn(
        "rounded-lg border p-3 text-sm",
        blocking ? "border-amber-400/30 bg-amber-400/10" : "border-info/30 bg-info/10",
      )}
    >
      <div className="flex items-center gap-2 font-medium text-foreground">
        <FileWarning aria-hidden className="size-4" />
        {title}
      </div>
      <p className="mt-1 text-muted-foreground">{reason}</p>
      {nextAction ? (
        <p className="mt-2 text-xs font-medium text-foreground">{ui("nextStep", { action: nextAction })}</p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  )
}
