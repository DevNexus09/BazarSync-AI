import type { ColumnDef } from "@tanstack/react-table"
import { Download } from "lucide-react"
import { useMemo, type MouseEvent } from "react"

import { Button } from "@/components/ui/button"
import { DataTable } from "@/components/ui/data-table"
import { StatusBadge } from "@/components/ui/status-badge"
import type { InventoryIntelligenceItem } from "@/types/inventory-intelligence"
import { formatNumber } from "@/utils/formatters"

import { StockRunwayBar } from "../components/StockRunwayBar"
import { t } from "../inventory-i18n"
import { daysUntil, matchesUrgency, shortDate, toCsv, type UrgencyFilter } from "../inventory-logic"
import type { ReorderDecisions } from "../use-reorder-decisions"

function download(rows: InventoryIntelligenceItem[]) {
  const url = URL.createObjectURL(new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" }))
  const link = document.createElement("a")
  link.href = url
  link.download = `reorders-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

const stop = (event: MouseEvent) => event.stopPropagation()
const selectClass = "h-9 rounded-lg border border-border bg-card/60 px-2 text-sm text-foreground"

export function ReorderTab({
  items,
  today,
  urgency,
  category,
  onUrgency,
  onCategory,
  onOpenProduct,
  decisions,
}: {
  items: InventoryIntelligenceItem[]
  today: Date
  urgency: UrgencyFilter
  category: string
  onUrgency: (value: UrgencyFilter) => void
  onCategory: (value: string) => void
  onOpenProduct: (productId: string) => void
  decisions: ReorderDecisions
}) {
  const categories = useMemo(() => [...new Set(items.map((item) => item.category).filter(Boolean))].sort() as string[], [items])
  const rows = items.filter((item) => matchesUrgency(item, urgency) && (!category || item.category === category))

  const columns: ColumnDef<InventoryIntelligenceItem, unknown>[] = [
    {
      id: "product",
      header: t("colProduct"),
      accessorFn: (row) => `${row.productName} ${row.category ?? ""}`,
      cell: ({ row }) => (
        <span className="flex flex-col gap-1">
          <span className="font-medium text-foreground">{row.original.productName}</span>
          <StatusBadge kind="risk" value={row.original.riskLevel} />
        </span>
      ),
    },
    {
      id: "runway",
      header: t("colRunway"),
      // Unknown runway sorts last.
      accessorFn: (row) => (row.daysRemaining == null ? Number.MAX_SAFE_INTEGER : row.daysRemaining),
      cell: ({ row }) => <StockRunwayBar item={row.original} />,
      enableGlobalFilter: false,
    },
    {
      id: "order",
      header: t("colOrder"),
      accessorFn: (row) => (row.reorderAction === "REORDER" ? row.recommendedQuantity ?? 0 : -1),
      cell: ({ row }) => (row.original.reorderAction === "REORDER" && row.original.recommendedQuantity ? formatNumber(row.original.recommendedQuantity) : "—"),
      enableGlobalFilter: false,
    },
    {
      id: "by",
      header: t("colBy"),
      accessorFn: (row) => row.reorderDeadline ?? "9999",
      cell: ({ row }) => {
        const deadline = row.original.reorderAction === "REORDER" ? row.original.reorderDeadline : null
        if (!deadline) return "—"
        return (daysUntil(deadline, today) ?? 1) <= 0 ? <span className="font-medium text-danger">{t("today")}</span> : shortDate(deadline)
      },
      enableGlobalFilter: false,
    },
    {
      id: "action",
      header: t("colAction"),
      enableSorting: false,
      enableGlobalFilter: false,
      cell: ({ row }) => <RowAction item={row.original} decisions={decisions} />,
    },
  ]

  return (
    <DataTable
      columns={columns}
      data={rows}
      getRowId={(row) => row.productId}
      onRowClick={(row) => onOpenProduct(row.productId)}
      initialSorting={[{ id: "runway", desc: false }]}
      searchLabel={t("searchProducts")}
      toolbar={
        <>
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            {t("urgency")}
            <select className={selectClass} value={urgency} onChange={(event) => onUrgency(event.target.value as UrgencyFilter)}>
              <option value="all">{t("all")}</option>
              <option value="out">{t("urgencyOut")}</option>
              <option value="week">{t("urgencyWeek")}</option>
              <option value="reorder">{t("urgencyReorder")}</option>
              <option value="ok">{t("urgencyOk")}</option>
            </select>
          </label>
          {categories.length ? (
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              {t("category")}
              <select className={selectClass} value={category} onChange={(event) => onCategory(event.target.value)}>
                <option value="">{t("all")}</option>
                {categories.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </label>
          ) : null}
          <Button variant="outline" size="sm" onClick={() => download(rows)} disabled={!rows.length}>
            <Download aria-hidden className="size-4" /> {t("exportCsv")}
          </Button>
        </>
      }
    />
  )
}

function RowAction({ item, decisions }: { item: InventoryIntelligenceItem; decisions: ReorderDecisions }) {
  const id = item.reorderRecommendationId
  const pending = id ? decisions.pending[id] : undefined
  if (pending) {
    return <span className="text-sm text-muted-foreground">{pending === "mark-ordered" ? t("ordered") : t("dismissed")}</span>
  }
  if (item.recommendationStatus === "ORDERED") return <span className="text-sm text-muted-foreground">{t("ordered")}</span>
  if (item.recommendationStatus === "DISMISSED") return <span className="text-sm text-muted-foreground">{t("dismissed")}</span>
  if (item.reorderAction !== "REORDER" || !id) return <StatusBadge kind="reorder" value="HOLD" />
  return (
    <span className="flex flex-wrap gap-1" onClick={stop} onKeyDown={(event) => event.stopPropagation()}>
      <Button size="sm" onClick={() => decisions.decide({ recommendationId: id, productName: item.productName, decision: "mark-ordered" })}>
        {t("ordered")}
      </Button>
      <Button size="sm" variant="outline" onClick={() => decisions.decide({ recommendationId: id, productName: item.productName, decision: "dismiss" })}>
        {t("dismiss")}
      </Button>
    </span>
  )
}
