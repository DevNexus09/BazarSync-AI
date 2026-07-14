import { FileWarning } from "lucide-react"

import type { DeadStockReadinessCheck } from "@/types/dead-stock-readiness"

export function MissingDataReason({
  title,
  check,
}: {
  title: string
  check: DeadStockReadinessCheck
}) {
  return (
    <div
      className={
        check.blocking
          ? "rounded-lg border border-amber-400/30 bg-amber-400/10 p-3 text-sm"
          : "rounded-lg border border-info/30 bg-info/10 p-3 text-sm"
      }
    >
      <div className="flex items-center gap-2 font-medium text-foreground">
        <FileWarning className="size-4" />
        {title}
      </div>
      <p className="mt-1 text-muted-foreground">{check.message}</p>
      {check.nextAction ? (
        <p className="mt-2 text-xs font-medium text-foreground">
          Next: {check.nextAction}
        </p>
      ) : null}
    </div>
  )
}
