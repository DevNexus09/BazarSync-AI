import {
  AlertTriangle,
  CheckCircle2,
  Flame,
  ShieldAlert,
} from "lucide-react"
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
} from "recharts"

import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/common/error-state"
import { cn } from "@/lib/utils"
import { AlertCategory, AlertSeverity, type Alert } from "@/types/alert"
import { formatNumber } from "@/utils/formatters"

type StockAlertCardProps = {
  alerts?: Alert[]
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}

const severityIcons = {
  [AlertSeverity.Low]: CheckCircle2,
  [AlertSeverity.Medium]: AlertTriangle,
  [AlertSeverity.High]: ShieldAlert,
  [AlertSeverity.Critical]: Flame,
}

const severityTone = {
<<<<<<< HEAD
  [AlertSeverity.Low]: "text-emerald-300",
  [AlertSeverity.Medium]: "text-amber-300",
  [AlertSeverity.High]: "text-rose-300",
  [AlertSeverity.Critical]: "text-rose-200",
=======
  [AlertSeverity.Low]: "text-emerald-600",
  [AlertSeverity.Medium]: "text-amber-600",
  [AlertSeverity.High]: "text-rose-600",
  [AlertSeverity.Critical]: "text-rose-700",
>>>>>>> develop
}

const severityLabel: Record<AlertSeverity, string> = {
  [AlertSeverity.Low]: "Low",
  [AlertSeverity.Medium]: "Medium",
  [AlertSeverity.High]: "High",
  [AlertSeverity.Critical]: "Critical",
}

export function StockAlertCard({
  alerts,
  isLoading,
  isError,
  onRetry,
}: StockAlertCardProps) {
  if (isLoading) {
    return (
<<<<<<< HEAD
      <div className="glass-panel p-4">
=======
      <div className="rounded-xl border bg-background p-4 shadow-sm">
>>>>>>> develop
        <div className="h-5 w-32 animate-pulse rounded bg-muted/60" />
        <div className="mt-3 space-y-2">
          {Array.from({ length: 3 }).map((_, index) => (
            <div
              key={`stock-alert-skeleton-${index}`}
              className="h-8 rounded-lg bg-muted/30"
            />
          ))}
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <ErrorState
        title="Stock alerts unavailable"
        message="We couldn't fetch the latest stock risk alerts."
        action={
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        }
      />
    )
  }

  const stockAlerts =
    alerts?.filter((alert) => alert.category === AlertCategory.StockRisk) ?? []
  const topAlerts = stockAlerts.slice(0, 3)

  const chartData = [
    {
      name: "Low",
      count: stockAlerts.filter((alert) => alert.severity === AlertSeverity.Low)
        .length,
    },
    {
      name: "Med",
      count: stockAlerts.filter(
        (alert) => alert.severity === AlertSeverity.Medium
      ).length,
    },
    {
      name: "High",
      count: stockAlerts.filter((alert) => alert.severity === AlertSeverity.High)
        .length,
    },
    {
      name: "Crit",
      count: stockAlerts.filter(
        (alert) => alert.severity === AlertSeverity.Critical
      ).length,
    },
  ]

  return (
<<<<<<< HEAD
    <div className="glass-panel p-4">
=======
    <div className="rounded-xl border bg-background p-4 shadow-sm">
>>>>>>> develop
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            Stock risk alerts
          </h3>
          <p className="text-xs text-muted-foreground">
            {formatNumber(stockAlerts.length)} active stock risk signals
          </p>
        </div>
      </div>

      {stockAlerts.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed bg-muted/30 p-4 text-xs text-muted-foreground">
          No stock risks detected. Inventory is stable.
        </div>
      ) : (
        <>
          <div className="mt-4 h-24">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <XAxis dataKey="name" tickLine={false} axisLine={false} />
                <Tooltip cursor={{ fill: "transparent" }} />
<<<<<<< HEAD
                <Bar dataKey="count" fill="#3B82F6" radius={[6, 6, 0, 0]} />
=======
                <Bar dataKey="count" fill="#6366F1" radius={[6, 6, 0, 0]} />
>>>>>>> develop
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 space-y-3">
            {topAlerts.map((alert) => {
              const Icon = severityIcons[alert.severity]
              return (
                <div
                  key={alert.id}
<<<<<<< HEAD
                  className="rounded-lg border border-border/60 bg-card/60 p-3"
=======
                  className="rounded-lg border bg-muted/20 p-3"
>>>>>>> develop
                >
                  <div className="flex items-start gap-2">
                    <Icon
                      className={cn(
                        "mt-0.5 size-4",
                        severityTone[alert.severity]
                      )}
                    />
                    <div>
                      <p className="text-xs font-semibold text-foreground">
                        {alert.title}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {alert.message}
                      </p>
                      <span className="mt-1 inline-flex text-[11px] font-semibold text-muted-foreground">
                        {severityLabel[alert.severity]} ·{" "}
                        {new Date(alert.createdAt).toLocaleTimeString()}
                      </span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}