import { useMemo, useState } from "react"
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  PackageSearch,
  RefreshCw,
  ShieldAlert,
  Truck,
} from "lucide-react"

import { ErrorState } from "@/components/common/error-state"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import {
  useInventoryIntelligenceSummary,
  useInventoryReorderList,
  useInventoryRisks,
  useProductInventoryIntelligence,
  useRunDailyInventoryWorkflow,
  useRunProductInventoryWorkflow,
} from "@/hooks/useInventoryIntelligence"
import { useProducts } from "@/hooks/use-products"
import { cn } from "@/lib/utils"
import type {
  InventoryIntelligenceItem,
  InventoryRiskLevel,
} from "@/types/inventory-intelligence"
import type { Product } from "@/types/product"
import { formatDateTime, formatNumber } from "@/utils/formatters"

const PAGE_LIMIT = 8

const riskStyles: Record<InventoryRiskLevel, string> = {
  LOW: "border-emerald-400/40 bg-emerald-400/10 text-emerald-200",
  MEDIUM: "border-amber-400/40 bg-amber-400/10 text-amber-200",
  HIGH: "border-orange-400/40 bg-orange-400/10 text-orange-200",
  CRITICAL: "border-red-400/40 bg-red-400/10 text-red-200",
}

const formatOptionalNumber = (value?: number | null, suffix = "") => {
  if (value == null || Number.isNaN(value)) {
    return "Not available"
  }
  return `${formatNumber(value)}${suffix}`
}

const formatDecimal = (value?: number | null, suffix = "") => {
  if (value == null || Number.isNaN(value)) {
    return "Not available"
  }
  return `${new Intl.NumberFormat("en-BD", {
    maximumFractionDigits: 1,
  }).format(value)}${suffix}`
}

const formatDate = (value?: string | null) => {
  if (!value) {
    return "Not available"
  }
  return new Intl.DateTimeFormat("en-BD", {
    dateStyle: "medium",
  }).format(new Date(`${value}T00:00:00`))
}

function RiskBadge({ level }: { level?: InventoryRiskLevel | null }) {
  if (!level) {
    return (
      <span className="rounded-full border border-slate-400/40 bg-slate-400/10 px-2 py-0.5 text-xs font-semibold text-slate-200">
        No risk yet
      </span>
    )
  }
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 text-xs font-semibold",
        riskStyles[level]
      )}
    >
      {level}
    </span>
  )
}

function MetricCard({
  label,
  value,
  helper,
  icon: Icon,
}: {
  label: string
  value: string
  helper: string
  icon: typeof ShieldAlert
}) {
  return (
    <div className="glass-panel p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            {label}
          </p>
          <p className="mt-2 text-2xl font-semibold text-foreground">{value}</p>
        </div>
        <div className="rounded-lg border border-border/70 bg-muted/30 p-2 text-primary">
          <Icon className="size-4" />
        </div>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">{helper}</p>
    </div>
  )
}

function ProductSelect({
  products,
  value,
  onChange,
}: {
  products: Product[]
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
      Product
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 min-w-[240px] rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none transition focus:border-primary"
      >
        <option value="">All products</option>
        {products.map((product) => (
          <option key={product.id} value={product.id}>
            {product.title}
          </option>
        ))}
      </select>
    </label>
  )
}

function RiskFilter({
  value,
  onChange,
}: {
  value: InventoryRiskLevel | "ALL"
  onChange: (value: InventoryRiskLevel | "ALL") => void
}) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
      Risk level
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as InventoryRiskLevel | "ALL")}
        className="h-10 rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none transition focus:border-primary"
      >
        <option value="ALL">All risks</option>
        <option value="CRITICAL">Critical</option>
        <option value="HIGH">High</option>
        <option value="MEDIUM">Medium</option>
        <option value="LOW">Low</option>
      </select>
    </label>
  )
}

function IntelligenceRows({
  title,
  items,
  total,
  isLoading,
  isError,
  emptyMessage,
  onRetry,
}: {
  title: string
  items?: InventoryIntelligenceItem[]
  total?: number
  isLoading: boolean
  isError: boolean
  emptyMessage: string
  onRetry: () => void
}) {
  return (
    <div className="glass-panel p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <span className="text-xs text-muted-foreground">
          {formatNumber(total ?? 0)} total
        </span>
      </div>
      {isLoading ? (
        <div className="mt-4 space-y-3">
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={`${title}-skeleton-${index}`}
              className="h-20 rounded-lg bg-muted/30"
            />
          ))}
        </div>
      ) : isError ? (
        <div className="mt-4">
          <ErrorState
            title={`${title} unavailable`}
            message="We couldn't load this inventory data."
            action={
              <Button variant="outline" size="sm" onClick={onRetry}>
                Retry
              </Button>
            }
          />
        </div>
      ) : !items || items.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed border-border/60 bg-muted/30 p-4 text-sm text-muted-foreground">
          {emptyMessage}
        </div>
      ) : (
        <div className="mt-4 divide-y divide-border/60">
          {items.map((item) => (
            <div
              key={`${title}-${item.productId}-${item.asOfDate ?? "latest"}`}
              className="grid gap-3 py-3 md:grid-cols-[minmax(0,1.6fr)_repeat(4,minmax(120px,1fr))]"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-foreground">
                  {item.productName}
                </p>
                <p className="text-xs text-muted-foreground">
                  {item.category || "Uncategorized"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Risk</p>
                <div className="mt-1 flex items-center gap-2">
                  <RiskBadge level={item.riskLevel} />
                  <span className="text-xs text-muted-foreground">
                    {formatDecimal(item.riskScore)}
                  </span>
                </div>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Days remaining</p>
                <p className="mt-1 text-sm font-medium text-foreground">
                  {formatDecimal(item.daysRemaining, " days")}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Reorder</p>
                <p className="mt-1 text-sm font-medium text-foreground">
                  {item.reorderAction?.replaceAll("_", " ") || "Not available"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Deadline</p>
                <p className="mt-1 text-sm font-medium text-foreground">
                  {formatDate(item.reorderDeadline)}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function InventoryIntelligencePage() {
  const productsQuery = useProducts()
  const products = productsQuery.data ?? []
  const [productId, setProductId] = useState("")
  const [riskLevel, setRiskLevel] = useState<InventoryRiskLevel | "ALL">("ALL")
  const filters = useMemo(
    () => ({
      productId: productId || undefined,
      riskLevel,
      limit: PAGE_LIMIT,
      offset: 0,
    }),
    [productId, riskLevel]
  )

  const summary = useInventoryIntelligenceSummary()
  const reorderList = useInventoryReorderList({
    ...filters,
    sort: "deadline",
  })
  const risks = useInventoryRisks(filters)
  const productIntelligence = useProductInventoryIntelligence(productId || undefined)
  const dailyWorkflow = useRunDailyInventoryWorkflow()
  const productWorkflow = useRunProductInventoryWorkflow()
  const selectedProduct = products.find((product) => product.id === productId)

  const isRefreshing =
    summary.isFetching ||
    reorderList.isFetching ||
    risks.isFetching ||
    productIntelligence.isFetching

  const refreshAll = () => {
    void summary.refetch()
    void reorderList.refetch()
    void risks.refetch()
    if (productId) {
      void productIntelligence.refetch()
    }
  }

  const runWorkflow = () => {
    if (productId) {
      productWorkflow.mutate(productId)
      return
    }
    dailyWorkflow.mutate()
  }

  const workflowRunning = dailyWorkflow.isPending || productWorkflow.isPending
  const workflowSuccess = dailyWorkflow.isSuccess || productWorkflow.isSuccess

  return (
    <div className="space-y-6">
      <PageHeader
        title="Inventory intelligence"
        description="Track Phase 6 inventory history, sales velocity, stockout prediction, reorder recommendations, risk scoring, and Telegram-alert readiness."
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={refreshAll}>
              <RefreshCw className={cn("size-4", isRefreshing && "animate-spin")} />
              Refresh
            </Button>
            <Button size="sm" onClick={runWorkflow} disabled={workflowRunning}>
              {workflowRunning ? (
                <RefreshCw className="size-4 animate-spin" />
              ) : (
                <ClipboardList className="size-4" />
              )}
              {productId ? "Recalculate product" : "Run daily workflow"}
            </Button>
          </div>
        }
      />

      {workflowSuccess ? (
        <div className="rounded-lg border border-emerald-400/40 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100">
          Inventory workflow has been queued. The dashboard will refresh as records are
          written.
        </div>
      ) : null}

      <div className="glass-panel flex flex-col gap-4 p-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
          <ProductSelect
            products={products}
            value={productId}
            onChange={setProductId}
          />
          <RiskFilter value={riskLevel} onChange={setRiskLevel} />
        </div>
        <p className="text-xs text-muted-foreground">
          Select a product to view its stockout prediction and reorder details.
        </p>
      </div>

      {summary.isError && !summary.data ? (
        <ErrorState
          title="Inventory intelligence unavailable"
          message="We couldn't load Phase 6 inventory intelligence."
          action={
            <Button variant="outline" size="sm" onClick={() => summary.refetch()}>
              Retry
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Active products"
            value={formatNumber(summary.data?.totalActiveProducts ?? 0)}
            helper={`Freshness: ${summary.data?.dataFreshnessStatus?.replaceAll("_", " ") ?? "No data"}`}
            icon={PackageSearch}
          />
          <MetricCard
            label="High or critical"
            value={formatNumber(
              (summary.data?.highRiskProducts ?? 0) +
                (summary.data?.criticalRiskProducts ?? 0)
            )}
            helper={`${formatNumber(summary.data?.criticalRiskProducts ?? 0)} critical risk products`}
            icon={ShieldAlert}
          />
          <MetricCard
            label="Need reorder"
            value={formatNumber(summary.data?.productsRequiringReorder ?? 0)}
            helper={`${formatNumber(summary.data?.productsAlreadyOutOfStock ?? 0)} already out of stock`}
            icon={Truck}
          />
          <MetricCard
            label="Insufficient data"
            value={formatNumber(summary.data?.insufficientDataProducts ?? 0)}
            helper={`Last calculated: ${formatDateTime(summary.data?.lastCalculationTime)}`}
            icon={AlertTriangle}
          />
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <IntelligenceRows
            title="Products to reorder"
            items={reorderList.data?.items}
            total={reorderList.data?.total}
            isLoading={reorderList.isLoading}
            isError={reorderList.isError}
            emptyMessage="No reorder recommendations are open for the selected filter."
            onRetry={() => reorderList.refetch()}
          />
        </div>
        <div className="xl:col-span-5">
          <div className="glass-panel p-4">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-foreground">
                Product intelligence
              </h3>
              {selectedProduct ? (
                <span className="truncate text-xs text-muted-foreground">
                  {selectedProduct.title}
                </span>
              ) : null}
            </div>
            {!productId ? (
              <div className="mt-4 rounded-lg border border-dashed border-border/60 bg-muted/30 p-4 text-sm text-muted-foreground">
                Choose a product to see inventory position, velocity, stockout
                prediction, risk score, and reorder action.
              </div>
            ) : productIntelligence.isLoading ? (
              <div className="mt-4 space-y-3">
                {Array.from({ length: 6 }).map((_, index) => (
                  <div
                    key={`product-intel-skeleton-${index}`}
                    className="h-10 rounded-lg bg-muted/30"
                  />
                ))}
              </div>
            ) : productIntelligence.isError ? (
              <div className="mt-4">
                <ErrorState
                  title="Product intelligence unavailable"
                  message="No Phase 6 calculation exists yet for this product, or it could not be loaded."
                  action={
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => productIntelligence.refetch()}
                    >
                      Retry
                    </Button>
                  }
                />
              </div>
            ) : (
              <div className="mt-4 space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs text-muted-foreground">Risk level</span>
                  <RiskBadge level={productIntelligence.data?.riskLevel} />
                </div>
                <Detail label="Risk score" value={formatDecimal(productIntelligence.data?.inventoryRiskScore)} />
                <Detail label="Stock on hand" value={formatOptionalNumber(productIntelligence.data?.quantityOnHand, " units")} />
                <Detail label="Reserved stock" value={formatOptionalNumber(productIntelligence.data?.quantityReserved, " units")} />
                <Detail label="Incoming stock" value={formatOptionalNumber(productIntelligence.data?.quantityIncoming, " units")} />
                <Detail label="Daily sales rate" value={formatDecimal(productIntelligence.data?.dailySalesRate, " units/day")} />
                <Detail label="Days remaining" value={formatDecimal(productIntelligence.data?.daysRemaining, " days")} />
                <Detail label="Predicted stockout" value={formatDate(productIntelligence.data?.predictedStockoutDate)} />
                <Detail label="Supplier lead time" value={formatOptionalNumber(productIntelligence.data?.supplierLeadTimeDays, " days")} />
                <Detail label="Recommended quantity" value={formatOptionalNumber(productIntelligence.data?.recommendedQuantity, " units")} />
                <Detail label="Reorder deadline" value={formatDate(productIntelligence.data?.reorderDeadline)} />
                <Detail label="Confidence" value={formatDecimal(productIntelligence.data?.confidenceScore, "%")} />
                <Detail label="Version" value={productIntelligence.data?.calculationVersion ?? "Not available"} />
                {productIntelligence.data?.explanation ? (
                  <div className="rounded-lg border border-border/70 bg-muted/20 p-3 text-xs text-muted-foreground">
                    {productIntelligence.data.explanation}
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </div>
        <div className="xl:col-span-12">
          <IntelligenceRows
            title="Inventory risks"
            items={risks.data?.items}
            total={risks.data?.total}
            isLoading={risks.isLoading}
            isError={risks.isError}
            emptyMessage="No inventory risk records match the selected filter."
            onRetry={() => risks.refetch()}
          />
        </div>
      </div>
    </div>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2">
      <span className="flex items-center gap-2 text-xs text-muted-foreground">
        <CheckCircle2 className="size-3.5" />
        {label}
      </span>
      <span className="text-right text-sm font-medium text-foreground">{value}</span>
    </div>
  )
}
