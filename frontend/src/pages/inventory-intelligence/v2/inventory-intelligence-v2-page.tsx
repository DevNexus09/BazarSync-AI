import { useMemo } from "react"
import { useSearchParams } from "react-router-dom"

import { InlineAlert } from "@/components/common/inline-alert"
import { LoadingState } from "@/components/common/loading-state"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { TrackRecordLine } from "@/components/track-record/TrackRecordLine"
import { EmptyState } from "@/components/ui/empty-state"
import { FreshnessPill } from "@/components/ui/freshness-pill"
import { UrlTabs } from "@/components/ui/tabs"
import { useDeadStockProducts, useDeadStockSummary } from "@/hooks/useDeadStock"
import {
  useInventoryIntelligenceSummary,
  useInventoryRisks,
  useRunDailyInventoryWorkflow,
} from "@/hooks/useInventoryIntelligence"

import { DataHealthBanner } from "./components/DataHealthBanner"
import { t } from "./inventory-i18n"
import { ProductInventoryDrawer } from "./components/ProductInventoryDrawer"
import type { UrgencyFilter } from "./inventory-logic"
import { DeadStockTab, type DeadStockShow } from "./tabs/DeadStockTab"
import { ReorderTab } from "./tabs/ReorderTab"
import { TodayTab } from "./tabs/TodayTab"
import { useReorderDecisions } from "./use-reorder-decisions"

// shortcut: one page of 200 rows per list, filtered in the browser; page through the API past that.
const RISK_FILTERS = { limit: 200, offset: 0 }
const DEAD_STOCK_FILTERS = { limit: 200, offset: 0, sort: "locked_capital" as const }
const URGENCY: UrgencyFilter[] = ["all", "out", "week", "reorder", "ok"]
const SHOW: DeadStockShow[] = ["all", "at-risk", "dead", "review"]

export default function InventoryIntelligenceV2Page() {
  const [params, setParams] = useSearchParams()
  const summary = useInventoryIntelligenceSummary()
  const risks = useInventoryRisks(RISK_FILTERS)
  const deadStockSummary = useDeadStockSummary()
  const deadStock = useDeadStockProducts(DEAD_STOCK_FILTERS)
  const workflow = useRunDailyInventoryWorkflow()
  const decisions = useReorderDecisions()
  const today = useMemo(() => new Date(), [])

  const update = (changes: Record<string, string | null>) =>
    setParams((current) => {
      const next = new URLSearchParams(current)
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value)
        else next.delete(key)
      }
      return next
    })
  const openProduct = (productId: string) => update({ product: productId })
  const urgencyParam = params.get("urgency") as UrgencyFilter | null
  const urgency = urgencyParam && URGENCY.includes(urgencyParam) ? urgencyParam : "all"
  const showParam = params.get("show") as DeadStockShow | null
  const show = showParam && SHOW.includes(showParam) ? showParam : "all"

  if (risks.isLoading || summary.isLoading) {
    return <LoadingState />
  }
  if (risks.isError) {
    return (
      <EmptyState
        title={t("loadFailed")}
        message={t("loadFailedMessage")}
        action={<Button variant="outline" onClick={() => risks.refetch()}>{t("tryAgain")}</Button>}
      />
    )
  }

  const items = risks.data?.items ?? []
  const deadRows = deadStock.data?.items ?? []
  const last = decisions.last

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("pageTitle")}
        description={t("pageSubtitle")}
        action={
          <FreshnessPill
            updatedAt={summary.data?.lastCalculationTime}
            onRefresh={() => workflow.mutate()}
            refreshing={workflow.isPending}
          />
        }
      />
      <TrackRecordLine type="REORDER" />
      {workflow.isSuccess ? <InlineAlert variant="success" message={t("recalcStarted")} /> : null}
      {workflow.isError ? <InlineAlert variant="error" message={t("recalcFailed")} /> : null}
      {decisions.error ? <InlineAlert variant="error" message={decisions.error} /> : null}

      <DataHealthBanner items={items} />

      {items.length === 0 && deadRows.length === 0 ? (
        <EmptyState
          title={t("noFigures")}
          message={t("noFiguresMessage")}
          action={<Button onClick={() => workflow.mutate()} disabled={workflow.isPending}>{t("calculateNow")}</Button>}
        />
      ) : (
        <UrlTabs
          label={t("tabsLabel")}
          defaultValue="today"
          tabs={[
            {
              value: "today",
              label: t("tabToday"),
              content: (
                <TodayTab
                  items={items}
                  deadStock={deadRows}
                  deadStockSummary={deadStockSummary.data}
                  today={today}
                  onOpenProduct={openProduct}
                  onShow={(tab, filter) => update(tab === "reorder" ? { tab, urgency: filter ?? null } : { tab, show: filter ?? null })}
                />
              ),
            },
            {
              value: "reorder",
              label: t("tabReorder"),
              content: (
                <ReorderTab
                  items={items}
                  today={today}
                  urgency={urgency}
                  category={params.get("category") ?? ""}
                  onUrgency={(value) => update({ urgency: value === "all" ? null : value })}
                  onCategory={(value) => update({ category: value || null })}
                  onOpenProduct={openProduct}
                  decisions={decisions}
                />
              ),
            },
            {
              value: "dead-stock",
              label: t("tabDeadStock"),
              content: deadStock.isError ? (
                <EmptyState title={t("deadStockLoadFailed")} action={<Button variant="outline" onClick={() => deadStock.refetch()}>{t("tryAgain")}</Button>} />
              ) : (
                <DeadStockTab
                  rows={deadRows}
                  summary={deadStockSummary.data}
                  show={show}
                  onShow={(value) => update({ show: value === "all" ? null : value })}
                  onOpenProduct={openProduct}
                />
              ),
            },
          ]}
        />
      )}

      <ProductInventoryDrawer productId={params.get("product")} onClose={() => update({ product: null })} decisions={decisions} />

      {last ? (
        <div role="status" className="fixed inset-x-4 bottom-4 z-50 mx-auto flex max-w-md items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3 text-sm shadow-2xl">
          <span className="text-foreground">
            {last.decision === "mark-ordered" ? t("markedOrdered", { name: last.productName }) : t("dismissedName", { name: last.productName })}
          </span>
          <Button size="sm" variant="outline" onClick={() => decisions.undo(last.recommendationId)}>
            {t("undo")}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
