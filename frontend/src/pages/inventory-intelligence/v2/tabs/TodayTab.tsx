import { AlertOctagon, AlertTriangle, CheckCircle2, Info } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardBody, CardHeader } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { KpiTile } from "@/components/ui/kpi-tile"
import type { DeadStockProduct, DeadStockSummary } from "@/types/dead-stock"
import type { InventoryIntelligenceItem } from "@/types/inventory-intelligence"
import { formatMoney, formatNumber } from "@/utils/formatters"

import { buildTodoList, inventoryKpis, type TodoItem } from "../inventory-logic"
import { t } from "../inventory-i18n"

const TONE_ICON = { danger: AlertOctagon, warning: AlertTriangle, info: Info }
const TONE_CLASS = { danger: "text-danger", warning: "text-warning", info: "text-info" }
const TONE_LABEL = { danger: t("toneUrgent"), warning: t("toneSoon"), info: t("toneReview") }

export function TodayTab({
  items,
  deadStock,
  deadStockSummary,
  today,
  onOpenProduct,
  onShow,
}: {
  items: InventoryIntelligenceItem[]
  deadStock: DeadStockProduct[]
  deadStockSummary: DeadStockSummary | undefined
  today: Date
  onOpenProduct: (productId: string) => void
  onShow: (tab: "reorder" | "dead-stock", filter?: string) => void
}) {
  const kpis = inventoryKpis(items)
  const todo = buildTodoList(items, deadStock, today)
  const cash =
    deadStockSummary?.totalLockedCapital != null && deadStockSummary.monetaryTotalsComparable
      ? formatMoney(deadStockSummary.totalLockedCapital, deadStockSummary.lockedCapitalCurrency ?? "BDT")
      : "—"

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile label={t("kpiOut")} value={formatNumber(kpis.outOfStock)} hint={t("kpiOutHint")} onClick={() => onShow("reorder", "out")} />
        <KpiTile label={t("kpiWeek")} value={formatNumber(kpis.runsOutWithinWeek)} hint={t("kpiWeekHint")} onClick={() => onShow("reorder", "week")} />
        <KpiTile label={t("kpiReorder")} value={formatNumber(kpis.reorderNow)} hint={t("kpiReorderHint")} onClick={() => onShow("reorder", "reorder")} />
        <KpiTile
          label={t("kpiCash")}
          value={cash}
          hint={deadStockSummary?.monetaryTotalsComparable === false ? t("kpiCashMixed") : t("kpiCashHint")}
          onClick={() => onShow("dead-stock")}
        />
      </div>

      <Card>
        <CardHeader title={t("todoTitle")} description={t("todoSubtitle")} />
        <CardBody>
          {todo.length === 0 ? (
            <EmptyState icon={CheckCircle2} title={t("nothingUrgent")} message={t("nothingUrgentMessage")} />
          ) : (
            <ol className="divide-y divide-border/50">
              {todo.map((entry: TodoItem) => {
                const Icon = TONE_ICON[entry.tone]
                return (
                  <li key={entry.key} className="flex items-center justify-between gap-3 py-2">
                    <span className="flex min-w-0 items-start gap-2 text-sm text-foreground">
                      <Icon aria-hidden className={`mt-0.5 size-4 shrink-0 ${TONE_CLASS[entry.tone]}`} />
                      <span>
                        <span className="sr-only">{TONE_LABEL[entry.tone]}: </span>
                        {entry.text}
                      </span>
                    </span>
                    <Button variant="outline" size="sm" onClick={() => onOpenProduct(entry.productId)}>
                      {t("details")}
                    </Button>
                  </li>
                )
              })}
            </ol>
          )}
          <div className="mt-3 text-right">
            <Button variant="link" size="sm" onClick={() => onShow("reorder")}>{t("viewAllReorders")}</Button>
          </div>
        </CardBody>
      </Card>
    </div>
  )
}
