import type { ColumnDef } from "@tanstack/react-table"
import { useMemo, useState } from "react"
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts"

import { DataTable } from "@/components/ui/data-table"
import { StatusBadge } from "@/components/ui/status-badge"
import { cn } from "@/lib/utils"
import type { DeadStockProduct, DeadStockRiskLevel, DeadStockSummary } from "@/types/dead-stock"
import { formatMoney } from "@/utils/formatters"

import { recoveryActionLabel } from "../inventory-logic"
import { t } from "../inventory-i18n"

export type DeadStockShow = "all" | "at-risk" | "dead" | "review"

const SHOW_OPTIONS: Array<{ value: DeadStockShow; label: string }> = [
  { value: "all", label: t("showAll") },
  { value: "at-risk", label: t("showAtRisk") },
  { value: "dead", label: t("showDead") },
  { value: "review", label: t("showReview") },
]

const matchesShow = (row: DeadStockProduct, show: DeadStockShow) =>
  show === "all" ||
  (show === "at-risk" && row.classification === "AT_RISK") ||
  (show === "dead" && row.classification === "DEAD_STOCK") ||
  (show === "review" && (row.primaryRecommendation === "MANUAL_REVIEW" || row.classification === "INSUFFICIENT_DATA"))

const selectClass = "h-9 rounded-lg border border-border bg-card/60 px-2 text-sm text-foreground"

const columns: ColumnDef<DeadStockProduct, unknown>[] = [
  {
    id: "product",
    header: t("colProduct"),
    accessorFn: (row) => `${row.productName} ${row.category ?? ""}`,
    cell: ({ row }) => (
      <span className="flex flex-col gap-1">
        <span className="font-medium text-foreground">{row.original.productName}</span>
        <StatusBadge kind="deadStock" value={row.original.classification} />
      </span>
    ),
  },
  {
    id: "idle",
    header: t("colIdle"),
    accessorFn: (row) => row.daysSinceLastSale ?? -1,
    cell: ({ row }) => (row.original.daysSinceLastSale == null ? <span className="text-muted-foreground">{t("noSales")}</span> : t("daysValue", { days: row.original.daysSinceLastSale })),
    enableGlobalFilter: false,
  },
  {
    id: "cash",
    header: t("colCash"),
    accessorFn: (row) => row.lockedCapital ?? -1,
    cell: ({ row }) =>
      row.original.lockedCapital == null ? (
        <span className="text-muted-foreground">{t("addCost")}</span>
      ) : (
        formatMoney(row.original.lockedCapital, row.original.lockedCapitalCurrency ?? "BDT")
      ),
    enableGlobalFilter: false,
  },
  {
    id: "action",
    header: t("colSuggested"),
    accessorFn: (row) => row.primaryRecommendation ?? "",
    cell: ({ row }) =>
      row.original.primaryRecommendation ? (
        <span className="capitalize">{recoveryActionLabel(row.original.primaryRecommendation).replace(/^an? /, "")}</span>
      ) : (
        <span className="text-muted-foreground">{t("needsCostsFees")}</span>
      ),
    enableGlobalFilter: false,
  },
  {
    id: "recovery",
    header: t("colRecovery"),
    accessorFn: (row) => row.potentialRecovery ?? -1,
    cell: ({ row }) =>
      row.original.potentialRecovery == null ? (
        <span className="text-muted-foreground">{t("needsFees")}</span>
      ) : (
        formatMoney(row.original.potentialRecovery, row.original.lockedCapitalCurrency ?? "BDT")
      ),
    enableGlobalFilter: false,
  },
]

export function DeadStockTab({
  rows,
  summary,
  show,
  onShow,
  onOpenProduct,
}: {
  rows: DeadStockProduct[]
  summary: DeadStockSummary | undefined
  show: DeadStockShow
  onShow: (value: DeadStockShow) => void
  onOpenProduct: (productId: string) => void
}) {
  const [risk, setRisk] = useState<DeadStockRiskLevel | "">("")
  const [category, setCategory] = useState("")
  const categories = useMemo(() => [...new Set(rows.map((row) => row.category).filter(Boolean))].sort() as string[], [rows])
  const visible = rows.filter((row) => matchesShow(row, show) && (!risk || row.riskLevel === risk) && (!category || row.category === category))
  const ages = Object.entries(summary?.ageDistribution ?? {}).map(([bucket, count]) => ({ bucket, count }))

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div role="group" aria-label={t("showLabel")} className="inline-flex rounded-lg border border-border bg-card/60 p-0.5">
          {SHOW_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={show === option.value}
              onClick={() => onShow(option.value)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                show === option.value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
        {ages.some((age) => age.count > 0) ? (
          <figure className="w-56">
            <figcaption className="text-xs text-muted-foreground">{t("stockAge")}</figcaption>
            <div className="h-16">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={ages} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
                  <XAxis dataKey="bucket" tick={{ fill: "rgb(var(--muted-foreground))", fontSize: 10 }} interval={0} tickLine={false} axisLine={false} />
                  <Tooltip
                    cursor={{ fill: "rgb(var(--muted) / 0.3)" }}
                    formatter={(value) => [t("productsCount", { count: String(value) }), ""]}
                    contentStyle={{ background: "rgb(var(--tooltip-background))", border: "1px solid rgb(var(--tooltip-border))", borderRadius: 8, color: "rgb(var(--tooltip-foreground))" }}
                    labelStyle={{ color: "rgb(var(--tooltip-foreground))" }}
                    itemStyle={{ color: "rgb(var(--tooltip-foreground))" }}
                  />
                  <Bar dataKey="count" fill="rgb(var(--chart-1))" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </figure>
        ) : null}
      </div>

      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground hover:text-foreground">{t("moreFilters")}</summary>
        <div className="mt-2 flex flex-wrap gap-3">
          <label className="flex items-center gap-2 text-muted-foreground">
            {t("risk")}
            <select className={selectClass} value={risk} onChange={(event) => setRisk(event.target.value as DeadStockRiskLevel | "")}>
              <option value="">{t("all")}</option>
              <option value="CRITICAL">{t("riskCritical")}</option>
              <option value="HIGH">{t("riskHigh")}</option>
              <option value="MEDIUM">{t("riskMedium")}</option>
              <option value="LOW">{t("riskLow")}</option>
            </select>
          </label>
          {categories.length ? (
            <label className="flex items-center gap-2 text-muted-foreground">
              {t("category")}
              <select className={selectClass} value={category} onChange={(event) => setCategory(event.target.value)}>
                <option value="">{t("all")}</option>
                {categories.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      </details>

      <DataTable
        columns={columns}
        data={visible}
        getRowId={(row) => row.productId}
        onRowClick={(row) => onOpenProduct(row.productId)}
        initialSorting={[{ id: "cash", desc: true }]}
        searchLabel={t("searchProducts")}
        empty={t("deadEmpty")}
      />
    </div>
  )
}
