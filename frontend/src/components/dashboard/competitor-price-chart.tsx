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
import type { CompetitorPricePoint } from "@/types/competitor"
import {
  formatCurrency,
  formatDateTime,
  formatShortDate,
} from "@/utils/formatters"

type CompetitorPriceChartProps = {
  data?: CompetitorPricePoint[]
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}

export function CompetitorPriceChart({
  data,
  isLoading,
  isError,
  onRetry,
}: CompetitorPriceChartProps) {
  if (isLoading) {
    return (
      <div className="glass-panel h-full p-4">
        <div className="h-5 w-40 animate-pulse rounded bg-muted/60" />
        <div className="mt-4 h-44 animate-pulse rounded-lg bg-muted/30" />
      </div>
    )
  }

  if (isError) {
    return (
      <ErrorState
        title="Competitor chart unavailable"
        message="We couldn't load the latest competitor price trend."
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
        <h3 className="text-sm font-semibold text-foreground">
          Competitor price trend
        </h3>
        <EmptyHint
          message="No competitor price history in the last 14 days. Track a competitor listing to start collecting prices."
          actionLabel="Track competitors"
          to="/app/competitors"
        />
      </div>
    )
  }

  return (
    <div className="glass-panel h-full p-4">
      <h3 className="text-sm font-semibold text-foreground">
        Competitor price trend
      </h3>
      <p className="text-xs text-muted-foreground">
        Live pricing movements across top competitors.
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
              tickFormatter={(value) => formatCurrency(Number(value))}
              width={72}
            />
            <Tooltip
              formatter={(value) => formatCurrency(Number(value))}
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
              dataKey="competitorPrice"
              name="Competitor"
              stroke="rgb(var(--warning))"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="sellerPrice"
              name="Your price"
              stroke="rgb(var(--foreground))"
              strokeWidth={2.5}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="marketAverage"
              name="Market avg"
              stroke="rgb(var(--chart-1))"
              strokeWidth={2}
              strokeDasharray="4 4"
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
