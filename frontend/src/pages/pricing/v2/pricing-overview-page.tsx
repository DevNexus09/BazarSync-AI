import type { ColumnDef } from "@tanstack/react-table"
import { ChevronRight, Package } from "lucide-react"
import { useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"

import { InlineAlert } from "@/components/common/inline-alert"
import { LoadingState } from "@/components/common/loading-state"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { DataTable } from "@/components/ui/data-table"
import { EmptyState } from "@/components/ui/empty-state"
import { FreshnessPill } from "@/components/ui/freshness-pill"
import { TrackRecordLine } from "@/components/track-record/TrackRecordLine"
import { KpiTile } from "@/components/ui/kpi-tile"
import { useMarketplaceFeePolicies, usePricingOverview } from "@/hooks/use-pricing-v2"
import { t } from "./pricing-i18n"
import {
  recalculateAllPricing,
  type MarketPosition,
  type PricingOverviewRow,
} from "@/services/pricing-v2-service"
import { formatMoney } from "@/utils/formatters"

import { PositionCell } from "./components/PositionCell"
import { pricingSetupSteps } from "./components/setup-steps"
import { SuggestionCell } from "./components/SuggestionCell"

type PositionFilter = "ALL" | MarketPosition | "MARGIN_AT_RISK"
type ActionFilter = "ALL" | "WAITING" | "PRICE_LOWER" | "PRICE_RAISE"

const money = (value: string | null) => formatMoney(value) ?? "—"

const columns: ColumnDef<PricingOverviewRow, unknown>[] = [
  {
    id: "title",
    header: t("colProduct"),
    accessorFn: (row) => `${row.title} ${row.sku ?? ""}`,
    cell: ({ row }) => (
      <span className="flex items-center gap-1 font-medium text-foreground">
        {row.original.title}
        <ChevronRight aria-hidden className="size-4 text-muted-foreground max-sm:hidden" />
      </span>
    ),
  },
  {
    id: "price",
    header: t("colYourPrice"),
    accessorFn: (row) => Number(row.currentPrice),
    cell: ({ row }) => money(row.original.currentPrice),
    enableGlobalFilter: false,
  },
  {
    id: "median",
    header: t("colMarket"),
    accessorFn: (row) => (row.marketMedianPrice == null ? -1 : Number(row.marketMedianPrice)),
    cell: ({ row }) => money(row.original.marketMedianPrice),
    enableGlobalFilter: false,
  },
  {
    id: "position",
    header: t("colPosition"),
    // Sort by distance from the market so the biggest gaps come first.
    accessorFn: (row) => (row.priceVsMedianRate == null ? -1 : Math.abs(Number(row.priceVsMedianRate))),
    cell: ({ row }) => <PositionCell position={row.original.position} rate={row.original.priceVsMedianRate} />,
    enableGlobalFilter: false,
  },
  {
    id: "suggestion",
    header: t("colSuggestion"),
    accessorFn: (row) => (row.recommendation?.isActionable ? 1 : 0),
    cell: ({ row }) => <SuggestionCell recommendation={row.original.recommendation} />,
    enableGlobalFilter: false,
  },
]

const selectClass = "h-9 rounded-lg border border-border bg-card/60 px-2 text-sm text-foreground"

export default function PricingOverviewPage() {
  const navigate = useNavigate()
  const overview = usePricingOverview()
  const feePolicies = useMarketplaceFeePolicies()
  const [position, setPosition] = useState<PositionFilter>("ALL")
  const [action, setAction] = useState<ActionFilter>("ALL")
  const recalculate = useMutation({ mutationFn: recalculateAllPricing })

  const rows = useMemo(() => {
    const items = overview.data?.items ?? []
    return items.filter((row) => {
      const positionOk =
        position === "ALL" || (position === "MARGIN_AT_RISK" ? row.marginAtRisk : row.position === position)
      const rec = row.recommendation
      const actionOk =
        action === "ALL" ||
        (action === "WAITING" ? Boolean(rec?.isActionable) : rec?.isActionable === true && rec.action === action)
      return positionOk && actionOk
    })
  }, [overview.data, position, action])

  if (overview.isLoading) {
    return <LoadingState />
  }
  if (overview.isError || !overview.data) {
    return (
      <EmptyState
        title={t("loadError")}
        message={overview.error instanceof Error ? overview.error.message : undefined}
        action={<Button variant="outline" onClick={() => overview.refetch()}>{t("tryAgain")}</Button>}
      />
    )
  }

  const { summary, total, items } = overview.data
  const steps = pricingSetupSteps(overview.data, feePolicies.data?.total)
  const nextStep = steps.find((step) => !step.done)
  const doneCount = steps.filter((step) => step.done).length

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("pricingTitle")}
        description={t("pricingSubtitle")}
        action={
          <FreshnessPill
            updatedAt={summary.lastCalculatedAt}
            onRefresh={() => recalculate.mutate()}
            refreshing={recalculate.isPending}
          />
        }
      />

      <TrackRecordLine type="PRICING" />
      {recalculate.isSuccess ? <InlineAlert variant="success" message={t("recalculating")} /> : null}
      {recalculate.isError ? <InlineAlert variant="error" message={t("loadError")} /> : null}

      {nextStep && feePolicies.isSuccess ? (
        <Card>
          <CardBody className="flex flex-wrap items-center justify-between gap-2 py-3">
            <span className="text-sm text-foreground">
              <span className="font-semibold">{t("setupProgress", { done: doneCount, total: steps.length })}</span>
              <span className="text-muted-foreground">{t("setupNext", { action: nextStep.actionLabel })}</span>
            </span>
            <Button asChild variant="outline" size="sm">
              <Link to="/app/pricing/setup">{t("finishSetup")}</Link>
            </Button>
          </CardBody>
        </Card>
      ) : null}

      {items.length === 0 ? (
        <EmptyState
          icon={Package}
          title={t("noProducts")}
          message={t("noProductsMessage")}
          action={<Button asChild><Link to="/app/products/new">{t("addProducts")}</Link></Button>}
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <KpiTile label={t("pricedAbove")} hint={t("pricedAboveHint")} value={summary.pricedAboveMarket} onClick={() => { setPosition("ABOVE_MARKET"); setAction("ALL") }} />
            <KpiTile label={t("pricedBelow")} hint={t("pricedBelowHint")} value={summary.pricedBelowMarket} onClick={() => { setPosition("BELOW_MARKET"); setAction("ALL") }} />
            <KpiTile label={t("marginAtRisk")} hint={t("marginAtRiskHint")} value={summary.marginAtRisk} onClick={() => { setPosition("MARGIN_AT_RISK"); setAction("ALL") }} />
            <KpiTile label={t("recommendationsWaiting")} hint={t("recommendationsWaitingHint")} value={summary.recommendationsWaiting} onClick={() => { setAction("WAITING"); setPosition("ALL") }} />
          </div>

          <Card>
            <CardBody>
              <DataTable
                columns={columns}
                data={rows}
                getRowId={(row) => row.productId}
                initialSorting={[{ id: "suggestion", desc: true }]}
                onRowClick={(row) => navigate(`/app/pricing/${row.productId}`)}
                searchLabel={t("searchProducts")}
                toolbar={
                  <>
                    <label className="flex items-center gap-2 text-sm text-muted-foreground">
                      {t("filterPosition")}
                      <select className={selectClass} value={position} onChange={(event) => setPosition(event.target.value as PositionFilter)}>
                        <option value="ALL">{t("all")}</option>
                        <option value="ABOVE_MARKET">{t("optAbove")}</option>
                        <option value="AT_MARKET">{t("optAt")}</option>
                        <option value="BELOW_MARKET">{t("optBelow")}</option>
                        <option value="NO_MARKET_DATA">{t("optNoData")}</option>
                        <option value="MARGIN_AT_RISK">{t("optMarginRisk")}</option>
                      </select>
                    </label>
                    <label className="flex items-center gap-2 text-sm text-muted-foreground">
                      {t("filterAction")}
                      <select className={selectClass} value={action} onChange={(event) => setAction(event.target.value as ActionFilter)}>
                        <option value="ALL">{t("all")}</option>
                        <option value="WAITING">{t("waiting")}</option>
                        <option value="PRICE_LOWER">{t("optLower")}</option>
                        <option value="PRICE_RAISE">{t("optRaise")}</option>
                      </select>
                    </label>
                  </>
                }
              />
              {total > items.length ? (
                <p className="mt-2 text-xs text-muted-foreground">{t("showingFirst", { shown: items.length, total })}</p>
              ) : null}
            </CardBody>
          </Card>
        </>
      )}
    </div>
  )
}
