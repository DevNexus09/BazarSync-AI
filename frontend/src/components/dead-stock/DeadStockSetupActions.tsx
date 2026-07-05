import { Link } from "react-router-dom"

import { Button } from "@/components/ui/button"
import type { DeadStockReadinessAction } from "@/types/dead-stock-readiness"

export function DeadStockSetupActions({
  actions,
  onRunAnalysis,
  runAnalysisPending,
}: {
  actions: DeadStockReadinessAction[]
  onRunAnalysis?: () => void
  runAnalysisPending?: boolean
}) {
  if (!actions.length) return null
  return (
    <div className="flex flex-wrap gap-2">
      {actions.map((action) => {
        if (action.key === "run_dead_stock_analysis" && onRunAnalysis) {
          return (
            <Button
              key={action.key}
              size="sm"
              onClick={onRunAnalysis}
              disabled={runAnalysisPending}
            >
              {runAnalysisPending ? "Queuing analysis..." : action.label}
            </Button>
          )
        }
        if (action.implemented && action.href) {
          return (
            <Button key={action.key} asChild size="sm" variant="outline">
              <Link to={action.href}>{action.label}</Link>
            </Button>
          )
        }
        return (
          <Button key={action.key} size="sm" variant="outline" disabled>
            {action.label} - Not implemented yet
          </Button>
        )
      })}
    </div>
  )
}
