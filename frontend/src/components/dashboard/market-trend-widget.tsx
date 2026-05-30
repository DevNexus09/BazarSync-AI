import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
} from "recharts"

import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/common/error-state"
import type { MarketTrendPoint } from "@/types/dashboard"

type MarketTrendWidgetProps = {
  data?: MarketTrendPoint[]
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}

export function MarketTrendWidget({
  data,
  isLoading,
  isError,
  onRetry,
}: MarketTrendWidgetProps) {
  if (isLoading) {
    return (
      <div className="glass-panel p-4">
        <div className="h-5 w-32 animate-pulse rounded bg-muted/60" />
        <div className="mt-4 h-40 animate-pulse rounded-lg bg-muted/30" />
      </div>
    )
  }

  if (isError) {
    return (
      <ErrorState
        title="Market trend unavailable"
        message="We couldn't load market trend signals."
        action={
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        }
      />
    )
  }

  if (!data || data.length === 0) {
    return (
      <div className="glass-panel p-4">
        <h3 className="text-sm font-semibold text-foreground">Market trends</h3>
        <div className="mt-4 rounded-lg border border-dashed bg-muted/30 p-4 text-xs text-muted-foreground">
          Trend signals will appear once market intelligence starts streaming.
        </div>
      </div>
    )
  }

  return (
    <div className="glass-panel p-4">
      <h3 className="text-sm font-semibold text-foreground">Market trends</h3>
      <p className="text-xs text-muted-foreground">
        Demand, urgency, and opportunity indices.
      </p>
      <div className="mt-4 h-48">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <XAxis dataKey="timestamp" tickLine={false} axisLine={false} />
            <YAxis tickLine={false} axisLine={false} width={40} />
            <Tooltip />
            <Legend />
            <Line
              type="monotone"
              dataKey="demandIndex"
              name="Demand"
              stroke="#38BDF8"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="urgencyIndex"
              name="Urgency"
              stroke="#F59E0B"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="opportunityIndex"
              name="Opportunity"
              stroke="#10B981"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
