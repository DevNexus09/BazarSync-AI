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
import { EmptyHint } from "@/components/dashboard/empty-hint"
import type { MarketTrendPoint } from "@/types/dashboard"
import { formatDateTime, formatShortDate } from "@/utils/formatters"

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
      <div className="glass-panel h-full p-4">
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
      <div className="glass-panel h-full p-4">
        <h3 className="text-sm font-semibold text-foreground">Market trends</h3>
        <EmptyHint
          message="No recommendations in the last 14 days. Trends are built from recommendation signals."
          actionLabel="Generate recommendations"
          to="/app/recommendations"
        />
      </div>
    )
  }

  return (
    <div className="glass-panel h-full p-4">
      <h3 className="text-sm font-semibold text-foreground">Market trends</h3>
      <p className="text-xs text-muted-foreground">
        Demand, urgency, and opportunity indices.
      </p>
      <div className="mt-3 h-48">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatShortDate}
              minTickGap={24}
              tickLine={false}
              axisLine={false}
              tick={{ fill: "rgb(var(--muted-foreground))", fontSize: 11 }}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              tick={{ fill: "rgb(var(--muted-foreground))", fontSize: 11 }}
              width={40}
            />
            <Tooltip
              labelFormatter={(label) => formatDateTime(String(label))}
              contentStyle={{
                background: "rgb(var(--tooltip-background))",
                border: "1px solid rgb(var(--tooltip-border))",
                borderRadius: "8px",
                color: "rgb(var(--tooltip-foreground))",
              }}
              itemStyle={{ color: "rgb(var(--tooltip-foreground))" }}
              labelStyle={{ color: "rgb(var(--tooltip-foreground))" }}
            />
            <Legend wrapperStyle={{ color: "rgb(var(--muted-foreground))" }} />
            <Line
              type="monotone"
              dataKey="demandIndex"
              name="Demand"
              stroke="rgb(var(--chart-2))"
              strokeWidth={2.5}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="urgencyIndex"
              name="Urgency"
              stroke="rgb(var(--chart-3))"
              strokeWidth={2.5}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="opportunityIndex"
              name="Opportunity"
              stroke="rgb(var(--chart-4))"
              strokeWidth={2.5}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
