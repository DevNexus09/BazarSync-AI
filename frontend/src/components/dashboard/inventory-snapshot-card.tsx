import { Link } from "react-router-dom"
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts"

import { EmptyHint } from "@/components/dashboard/empty-hint"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { InventoryIntelligenceSummary } from "@/types/inventory-intelligence"
import { formatDateTime, formatNumber } from "@/utils/formatters"

type InventorySnapshotCardProps = {
  inventory?: InventoryIntelligenceSummary
  marginAtRisk?: number
  isLoading: boolean
  isError: boolean
}

const RISK_SEGMENTS = [
  { key: "criticalRiskProducts", label: "Critical", color: "rgb(var(--danger))" },
  { key: "highRiskProducts", label: "High", color: "rgb(var(--warning))" },
  { key: "mediumRiskProducts", label: "Medium", color: "rgb(var(--chart-2))" },
  { key: "lowRiskProducts", label: "Low", color: "rgb(var(--success))" },
  {
    key: "insufficientDataProducts",
    label: "Not enough data",
    color: "rgb(var(--muted-foreground) / 0.35)",
  },
] as const

export function InventorySnapshotCard({
  inventory,
  marginAtRisk,
  isLoading,
  isError,
}: InventorySnapshotCardProps) {
  const segments = RISK_SEGMENTS.map((segment) => ({
    ...segment,
    value: inventory?.[segment.key] ?? 0,
  }))
  const total = segments.reduce((sum, segment) => sum + segment.value, 0)

  const counts: { label: string; value?: number }[] = [
    { label: "Need reorder", value: inventory?.productsRequiringReorder },
    { label: "Out of stock", value: inventory?.productsAlreadyOutOfStock },
    { label: "Margin at risk", value: marginAtRisk },
  ]

  return (
    <div className="glass-panel flex h-full flex-col p-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-foreground">Stock risk</h3>
        <Button variant="outline" size="xs" asChild>
          <Link to="/app/inventory-intelligence">Open inventory</Link>
        </Button>
      </div>

      {isLoading ? (
        <div className="mt-4 h-40 animate-pulse rounded-lg bg-muted/30" />
      ) : isError && !inventory ? (
        <EmptyHint message="Inventory data couldn't be loaded. Try syncing again." />
      ) : total === 0 ? (
        <EmptyHint
          message="No inventory risk calculated yet. Run the inventory workflow to score your products."
          actionLabel="Open inventory"
          to="/app/inventory-intelligence"
        />
      ) : (
        <div className="mt-4 flex flex-col items-center gap-5 sm:flex-row">
          <div className="relative size-36 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={segments.filter((segment) => segment.value > 0)}
                  dataKey="value"
                  nameKey="label"
                  innerRadius="68%"
                  outerRadius="100%"
                  paddingAngle={2}
                  stroke="none"
                  isAnimationActive={false}
                >
                  {segments
                    .filter((segment) => segment.value > 0)
                    .map((segment) => (
                      <Cell key={segment.key} fill={segment.color} />
                    ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    background: "rgb(var(--tooltip-background))",
                    border: "1px solid rgb(var(--tooltip-border))",
                    borderRadius: "8px",
                    color: "rgb(var(--tooltip-foreground))",
                  }}
                  itemStyle={{ color: "rgb(var(--tooltip-foreground))" }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-2xl font-semibold tabular-nums text-foreground">
                {formatNumber(total)}
              </span>
              <span className="text-[11px] text-muted-foreground">products</span>
            </div>
          </div>
          <ul className="w-full space-y-1.5 text-xs">
            {segments.map((segment) => (
              <li key={segment.key} className="flex items-center gap-2">
                <span
                  aria-hidden
                  className="size-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: segment.color }}
                />
                <span className="text-muted-foreground">{segment.label}</span>
                <span className="ml-auto font-semibold tabular-nums text-foreground">
                  {formatNumber(segment.value)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <dl className="mt-5 grid grid-cols-3 gap-3 border-t border-border/50 pt-4 text-xs">
        {counts.map((count) => (
          <div key={count.label}>
            <dt className="text-muted-foreground">{count.label}</dt>
            <dd
              className={cn(
                "mt-1 text-lg font-semibold tabular-nums",
                count.value == null
                  ? "text-muted-foreground"
                  : count.value > 0
                    ? "text-rose-300"
                    : "text-foreground"
              )}
            >
              {count.value == null ? "—" : formatNumber(count.value)}
            </dd>
          </div>
        ))}
      </dl>

      <p className="mt-auto pt-4 text-[11px] text-muted-foreground">
        {inventory?.lastCalculationTime
          ? `Calculated ${formatDateTime(inventory.lastCalculationTime)} · data ${inventory.dataFreshnessStatus.toLowerCase()}`
          : "Not calculated yet"}
      </p>
    </div>
  )
}
