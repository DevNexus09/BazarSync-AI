import type { DeadStockReadinessCheck } from "@/types/dead-stock-readiness"

export function UnavailableValueWithReason({
  label,
  check,
  fallback,
}: {
  label: string
  check?: DeadStockReadinessCheck
  fallback?: string
}) {
  return (
    <div>
      <div className="font-medium text-foreground">{label} unavailable</div>
      <p className="mt-1 max-w-[28rem] text-xs text-muted-foreground">
        {check?.nextAction || check?.message || fallback || "Required source data is missing."}
      </p>
    </div>
  )
}
