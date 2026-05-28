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
import type { CompetitorPricePoint } from "@/types/competitor"
import { formatCurrency } from "@/utils/formatters"

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
      <div className="rounded-xl border bg-background p-4 shadow-sm">
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
      <div className="rounded-xl border bg-background p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-foreground">
          Competitor price trend
        </h3>
        <div className="mt-4 rounded-lg border border-dashed bg-muted/30 p-4 text-xs text-muted-foreground">
          No price history yet. Once competitor data streams in, trends will
          appear here.
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-xl border bg-background p-4 shadow-sm">
      <h3 className="text-sm font-semibold text-foreground">
        Competitor price trend
      </h3>
      <p className="text-xs text-muted-foreground">
        Live pricing movements across top competitors.
      </p>
      <div className="mt-4 h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <XAxis dataKey="timestamp" tickLine={false} axisLine={false} />
            <YAxis
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => formatCurrency(Number(value))}
              width={72}
            />
            <Tooltip
              formatter={(value) => formatCurrency(Number(value))}
              labelFormatter={(label) => `Time: ${label}`}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="competitorPrice"
              name="Competitor"
              stroke="#F97316"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="sellerPrice"
              name="Your price"
              stroke="#6366F1"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="marketAverage"
              name="Market avg"
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