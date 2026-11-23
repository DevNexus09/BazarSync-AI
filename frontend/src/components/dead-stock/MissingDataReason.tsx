import { MissingData } from "@/components/ui/empty-state"
import type { DeadStockReadinessCheck } from "@/types/dead-stock-readiness"

export function MissingDataReason({
  title,
  check,
}: {
  title: string
  check: DeadStockReadinessCheck
}) {
  return (
    <MissingData
      title={title}
      reason={check.message}
      nextAction={check.nextAction}
      blocking={check.blocking}
    />
  )
}
