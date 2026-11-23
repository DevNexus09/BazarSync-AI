import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from "recharts"
import { useState } from "react"

import { LoadingState } from "@/components/common/loading-state"
import { Button } from "@/components/ui/button"
import { Drawer } from "@/components/ui/drawer"
import { EmptyState, MissingData } from "@/components/ui/empty-state"
import { HowCalculated } from "@/components/ui/how-calculated"
import { StatusBadge } from "@/components/ui/status-badge"
import { useDeadStockReadiness, useProductDeadStockIntelligence, useRecoverySimulation } from "@/hooks/useDeadStock"
import { useProductInventoryIntelligence } from "@/hooks/useInventoryIntelligence"
import { useTrackRecord } from "@/hooks/use-track-record"
import { confidenceBand } from "@/services/recommendation-outcome-service"
import { getProductInventoryHistory } from "@/services/inventory-intelligence-service"
import type { ProductDeadStockIntelligence } from "@/types/dead-stock"
import type { DeadStockReadiness } from "@/types/dead-stock-readiness"
import type { ProductInventoryIntelligence } from "@/types/inventory-intelligence"
import { formatMoney, formatNumber } from "@/utils/formatters"

import { recoveryActionLabel, runsOutText, shortDate } from "../inventory-logic"
import { t } from "../inventory-i18n"
import type { ReorderDecisions } from "../use-reorder-decisions"

export function ProductInventoryDrawer({
  productId,
  onClose,
  decisions,
}: {
  productId: string | null
  onClose: () => void
  decisions: ReorderDecisions
}) {
  const intelligence = useProductInventoryIntelligence(productId ?? undefined)
  const data = intelligence.data
  return (
    <Drawer
      open={Boolean(productId)}
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={data?.productName ?? t("drawerFallbackTitle")}
    >
      {intelligence.isLoading ? (
        <LoadingState />
      ) : intelligence.isError || !data || !productId ? (
        <EmptyState title={t("drawerLoadFailed")} message={t("drawerLoadFailedMessage")} />
      ) : (
        <DrawerBody productId={productId} data={data} decisions={decisions} />
      )}
    </Drawer>
  )
}

function DrawerBody({ productId, data, decisions }: { productId: string; data: ProductInventoryIntelligence; decisions: ReorderDecisions }) {
  const deadStock = useProductDeadStockIntelligence(productId)
  const readiness = useDeadStockReadiness(productId)
  const history = useQuery({
    queryKey: ["inventory-intelligence", "history", productId],
    queryFn: () => getProductInventoryHistory(productId),
  })
  const runway = runsOutText(data)
  const leadDefaulted = data.supplierLeadTimeDefaulted === true
  const slow = deadStock.data?.classification && !["HEALTHY", "INSUFFICIENT_DATA"].includes(deadStock.data.classification)

  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge kind="risk" value={data.riskLevel} />
        <span className="font-medium text-foreground">{runway ?? t("notEnoughSales")}</span>
      </div>

      <dl className="space-y-1">
        <div>
          <dt className="sr-only">{t("srStock")}</dt>
          <dd className="text-foreground">
            {data.quantityAvailable == null
              ? t("noStockCount")
              : t("stockLine", { available: formatNumber(data.quantityAvailable), onHand: formatNumber(data.quantityOnHand ?? 0), held: formatNumber(data.quantityReserved ?? 0) })}
          </dd>
        </div>
        <div>
          <dt className="sr-only">{t("srSales")}</dt>
          <dd className="text-muted-foreground">
            {data.dailySalesRate == null ? t("paceUnknown") : t("pace", { rate: formatNumber(Math.round(data.dailySalesRate * 10) / 10) })}
            {data.quantityIncoming ? t("incoming", { count: formatNumber(data.quantityIncoming) }) : ""}
          </dd>
        </div>
      </dl>

      <ReorderBox data={data} decisions={decisions} />

      {leadDefaulted ? (
        <MissingData
          title={t("leadMissingTitle")}
          reason={t("leadMissingReason")}
          action={<Button asChild variant="outline" size="sm"><Link to={`/app/products/${productId}/edit`}>{t("addSupplierLeadTime")}</Link></Button>}
        />
      ) : null}

      <StockTrend points={history.data} />

      {slow && deadStock.data ? <RecoveryOptions productId={productId} intelligence={deadStock.data} readiness={readiness.data} /> : null}

      <HowCalculated
        formula={t("howFormula")}
        version={data.calculationVersion}
        calculatedAt={data.lastUpdatedAt}
        assumptions={[
          data.velocityWindowDays ? t("assumptionWindow", { days: data.velocityWindowDays }) : t("assumptionNoWindow"),
          data.supplierLeadTimeDays != null
            ? t("assumptionLead", { days: data.supplierLeadTimeDays, defaulted: leadDefaulted ? t("assumptionLeadDefault") : "" })
            : t("assumptionNoLead"),
          data.safetyBufferDays != null ? t("assumptionBuffer", { days: data.safetyBufferDays }) : t("assumptionNoBuffer"),
          data.confidenceScore != null ? t("assumptionConfidence", { percent: Math.round(data.confidenceScore) }) : t("assumptionNoConfidence"),
        ]}
      />
    </div>
  )
}

function ReorderBox({ data, decisions }: { data: ProductInventoryIntelligence; decisions: ReorderDecisions }) {
  const trackRecord = useTrackRecord("REORDER")
  const band = trackRecord.data?.enabled && data.confidenceScore != null ? trackRecord.data.bands[confidenceBand(data.confidenceScore)] : null
  const measured = band?.reliable && band.hitRate != null ? Math.round(band.hitRate * 100) : null
  const id = data.reorderRecommendationId
  const pending = id ? decisions.pending[id] : undefined
  const status = pending === "mark-ordered" ? "ORDERED" : pending === "dismiss" ? "DISMISSED" : data.recommendationStatus

  if (data.reorderAction !== "REORDER") {
    return (
      <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
        <p className="font-medium text-foreground">{t("noReorder")}</p>
        {data.explanation ? <p className="mt-1 text-muted-foreground">{data.explanation}</p> : null}
      </div>
    )
  }
  const by = data.reorderDeadline ? shortDate(data.reorderDeadline) : t("soon")
  return (
    <section aria-label={t("srReorder")} className="rounded-lg border border-border/60 bg-muted/20 p-3">
      <p className="text-base font-semibold text-foreground">
        {t("orderBy", { quantity: formatNumber(data.recommendedQuantity ?? 0), date: by })}
      </p>
      {data.supplierLeadTimeDays != null ? (
        <p className="mt-1 text-muted-foreground">
          {t("covers", { lead: data.supplierLeadTimeDays })}
          {data.safetyStockUnits != null && data.safetyStockServiceLevel != null
            ? t("coversBuffer", { units: formatNumber(data.safetyStockUnits), level: Math.round(data.safetyStockServiceLevel * 100) })
            : data.safetyBufferDays != null
              ? t("coversBufferDays", { days: data.safetyBufferDays })
              : ""}
        </p>
      ) : null}
      {status === "ORDERED" ? (
        <p className="mt-2 font-medium text-success">{t("markedAsOrdered")}</p>
      ) : status === "DISMISSED" ? (
        <p className="mt-2 text-muted-foreground">{t("dismissed")}</p>
      ) : id ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" onClick={() => decisions.decide({ recommendationId: id, productName: data.productName, decision: "mark-ordered" })}>
            {t("markOrdered")}
          </Button>
          <Button size="sm" variant="outline" onClick={() => decisions.decide({ recommendationId: id, productName: data.productName, decision: "dismiss" })}>
            {t("dismiss")}
          </Button>
        </div>
      ) : null}
      {measured != null ? (
        <p className="mt-2 text-xs text-muted-foreground">{t("calibrated", { percent: measured })}</p>
      ) : null}
      <p className="mt-2 text-xs text-muted-foreground">{t("orderNote")}</p>
    </section>
  )
}

function StockTrend({ points }: { points: Array<{ date: string; available: number }> | undefined }) {
  if (!points || points.length < 2) {
    return <p className="text-muted-foreground">{t("trendEmpty")}</p>
  }
  return (
    <figure>
      <figcaption className="text-xs text-muted-foreground">{t("trendCaption")}</figcaption>
      <div className="h-16">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
            <YAxis hide domain={[0, "auto"]} />
            <Tooltip
              labelFormatter={(_, payload) => (payload?.[0]?.payload?.date ? shortDate(payload[0].payload.date) : "")}
              formatter={(value) => [t("availableValue", { count: String(value) }), ""]}
              contentStyle={{ background: "rgb(var(--tooltip-background))", border: "1px solid rgb(var(--tooltip-border))", borderRadius: 8, color: "rgb(var(--tooltip-foreground))" }}
              labelStyle={{ color: "rgb(var(--tooltip-foreground))" }}
              itemStyle={{ color: "rgb(var(--tooltip-foreground))" }}
            />
            <Line dataKey="available" stroke="rgb(var(--chart-1))" strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  )
}

const RULE_TEXT: Record<string, string> = {
  NO_VALID_SALES: t("ruleNoValidSales"),
  LOW_SALES_VELOCITY: t("ruleLowVelocity"),
  INVENTORY_AGE_THRESHOLD: t("ruleAge"),
  INVENTORY_AGE_ESTIMATED: t("ruleAgeEstimated"),
  EXCESSIVE_INVENTORY_COVERAGE: t("ruleCoverage"),
  LOW_VISIBILITY: t("ruleVisibility"),
  INSUFFICIENT_REQUIRED_DATA: t("ruleMissingData"),
}

function RecoveryOptions({
  productId,
  intelligence,
  readiness,
}: {
  productId: string
  intelligence: ProductDeadStockIntelligence
  readiness: DeadStockReadiness | undefined
}) {
  const [discount, setDiscount] = useState("0.10")
  const simulation = useRecoverySimulation(productId)
  const currency = intelligence.lockedCapitalCurrency ?? "BDT"
  const blocker = readiness && !readiness.canEstimatePotentialRecovery
    ? Object.values(readiness.checks).find((check) => check.blocking && check.reasonCode)?.message ?? t("recoveryBlocked")
    : null

  return (
    <details className="rounded-lg border border-border/60 bg-muted/20">
      <summary className="cursor-pointer px-3 py-2 font-medium text-foreground">{t("recoveryTitle")}</summary>
      <div className="space-y-3 px-3 pb-3">
        <p className="text-foreground">
          {intelligence.primaryRecoveryRecommendation
            ? intelligence.recommendedDiscountRate != null
              ? t("suggestedDiscount", { action: recoveryActionLabel(intelligence.primaryRecoveryRecommendation), percent: Math.round(intelligence.recommendedDiscountRate * 100) })
              : t("suggested", { action: recoveryActionLabel(intelligence.primaryRecoveryRecommendation) })
            : t("noSafeRecovery")}
        </p>
        {intelligence.lockedCapital != null ? (
          <p className="text-muted-foreground">{t("cashStuck", { amount: formatMoney(intelligence.lockedCapital, currency) ?? "—" })}</p>
        ) : null}
        {intelligence.potentialRecoveredCashLow != null && intelligence.potentialRecoveredCashHigh != null ? (
          <p className="text-muted-foreground">
            {t("expectedRecover", { low: formatMoney(intelligence.potentialRecoveredCashLow, currency) ?? "—", high: formatMoney(intelligence.potentialRecoveredCashHigh, currency) ?? "—" })}
          </p>
        ) : null}
        {intelligence.triggeredRules.length ? (
          <div>
            <h4 className="text-xs font-semibold text-muted-foreground">{t("whyTitle")}</h4>
            <ul className="mt-1 list-disc pl-4 text-foreground">
              {intelligence.triggeredRules.map((rule) => (
                <li key={rule}>{RULE_TEXT[rule] ?? rule.toLowerCase().replace(/_/g, " ")}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            {t("tryDiscount")}
            <select className="h-9 rounded-lg border border-border bg-card/60 px-2 text-sm text-foreground" value={discount} onChange={(event) => setDiscount(event.target.value)}>
              {["0.05", "0.10", "0.15", "0.20"].map((value) => (
                <option key={value} value={value}>{Math.round(Number(value) * 100)}%</option>
              ))}
            </select>
          </label>
          <Button
            size="sm"
            variant="outline"
            disabled={Boolean(blocker) || simulation.isPending}
            onClick={() =>
              simulation.mutate({
                action: intelligence.primaryRecoveryRecommendation ?? "DISCOUNT",
                candidateDiscount: Number(discount),
                eligibleQuantity: intelligence.eligibleUnsoldQuantity ?? undefined,
              })
            }
          >
            {t("estimateRecovery")}
          </Button>
        </div>
        {blocker ? <p className="text-warning">{blocker}</p> : null}
        {simulation.isError ? <p className="text-danger">{t("estimateFailed")}</p> : null}
        {simulation.data ? (
          <p className="text-foreground">
            {t("estimateResult", { percent: Math.round(Number(discount) * 100), amount: formatMoney(simulation.data.potentialRecoveredCash, currency) ?? "—" })}
          </p>
        ) : null}
        <p className="text-xs text-muted-foreground">{t("estimatesOnly")}</p>
      </div>
    </details>
  )
}
