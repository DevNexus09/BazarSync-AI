import { AlertTriangle } from "lucide-react"

import { DeadStockSetupActions } from "@/components/dead-stock/DeadStockSetupActions"
import { MissingDataReason } from "@/components/dead-stock/MissingDataReason"
import type { DeadStockReadiness } from "@/types/dead-stock-readiness"

const labels: Record<string, string> = {
  product_cost: "Missing cost",
  selling_price: "Missing selling price",
  currency: "Missing currency",
  marketplace: "Missing marketplace",
  inventory_age_source: "Missing inventory age source",
  sales_history: "Missing sales history",
  marketplace_fee_policy: "Missing marketplace fee policy",
  pricing_policy: "Missing pricing policy",
  visibility_data: "Missing visibility",
  dead_stock_assessment: "Dead-stock analysis pending",
  risk_score: "Risk scoring pending",
  recovery_recommendation: "Recovery recommendation pending",
  capital_recovery_estimate: "Capital recovery estimate pending",
  phase9_pipeline: "Phase 9 recalculation pending",
}

export function DeadStockReadinessPanel({
  readiness,
  isError,
  onRunAnalysis,
  runAnalysisPending,
}: {
  readiness?: DeadStockReadiness
  isError?: boolean
  onRunAnalysis?: () => void
  runAnalysisPending?: boolean
}) {
  if (isError) {
    return (
      <section className="glass-panel border-amber-400/40 p-4" aria-label="Dead stock readiness">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <AlertTriangle className="size-4" />
          Dead stock readiness unavailable
        </h3>
        <p className="mt-2 text-sm text-muted-foreground">
          The dashboard can still render, but setup guidance could not be loaded.
        </p>
      </section>
    )
  }

  if (!readiness) return null
  const checks = Object.entries(readiness.checks).filter(
    ([, check]) => check.reasonCode && check.status !== "OK"
  )
  if (!checks.length) return null
  const blocking = checks.filter(([, check]) => check.blocking)
  const optional = checks.filter(([, check]) => !check.blocking)

  return (
    <section className="glass-panel p-4" aria-label="Dead stock readiness">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <AlertTriangle className="size-4 text-amber-200" />
            Dead stock analysis setup incomplete
          </h3>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            Some required business data is missing. Add the missing data below to
            unlock inventory age, risk score, locked capital, recovery
            recommendations, and potential recovery estimates.
          </p>
        </div>
        <DeadStockSetupActions
          actions={readiness.nextActions}
          onRunAnalysis={onRunAnalysis}
          runAnalysisPending={runAnalysisPending}
        />
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        {blocking.map(([key, check]) => (
          <MissingDataReason key={key} title={labels[key] ?? key} check={check} />
        ))}
        {optional.map(([key, check]) => (
          <MissingDataReason key={key} title={labels[key] ?? key} check={check} />
        ))}
      </div>
    </section>
  )
}
