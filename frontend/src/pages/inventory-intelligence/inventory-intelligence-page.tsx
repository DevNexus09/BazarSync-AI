import { useMemo, useState } from "react"
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Coins,
  FileWarning,
  PackageSearch,
  RefreshCw,
  ShieldAlert,
  Truck,
} from "lucide-react"
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

import { ErrorState } from "@/components/common/error-state"
import { PageHeader } from "@/components/common/page-header"
import { DeadStockReadinessPanel } from "@/components/dead-stock/DeadStockReadinessPanel"
import { UnavailableValueWithReason } from "@/components/dead-stock/UnavailableValueWithReason"
import { Button } from "@/components/ui/button"
import {
  useDeadStockProducts,
  useDeadStockReadiness,
  useDeadStockRecalculation,
  useDeadStockSummary,
  useProductDeadStockIntelligence,
  useRecoverySimulation,
} from "@/hooks/useDeadStock"
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
import type {
  DeadStockClassification,
  DeadStockDataStatus,
  DeadStockProduct,
  DeadStockRiskLevel,
  ProductDeadStockIntelligence,
  RecoveryAction,
} from "@/types/dead-stock"
import type { DeadStockReadiness } from "@/types/dead-stock-readiness"
import { formatCurrency, formatDateTime, formatNumber } from "@/utils/formatters"

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

const currency = (value?: number | null) =>
  value == null || Number.isNaN(value) ? "Estimate unavailable" : formatCurrency(value)

const labelize = (value?: string | null) =>
  value ? value.replaceAll("_", " ").toLowerCase().replace(/(^|\s)\S/g, (s) => s.toUpperCase()) : "Not available"

function RiskBadge({ level }: { level?: InventoryRiskLevel | null }) {
  if (!level) {
    return (
      <span className="rounded-full border border-border-strong/40 bg-muted/60 px-2 py-0.5 text-xs font-semibold text-muted-foreground">
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

function DeadStockRiskBadge({ level }: { level?: DeadStockRiskLevel | null }) {
  return (
    <span className="rounded-full border border-border bg-muted/30 px-2 py-0.5 text-xs font-semibold text-foreground">
      {level ? `${level} risk` : "Risk unavailable"}
    </span>
  )
}

function SelectFilter<T extends string>({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: T
  onChange: (value: T) => void
  options: { value: T; label: string }[]
}) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
        className="h-10 rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none transition focus:border-primary"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function DeadStockTable({
  rows,
  total,
  isLoading,
  isError,
  offset,
  setOffset,
  onRetry,
}: {
  rows?: DeadStockProduct[]
  total?: number
  isLoading: boolean
  isError: boolean
  offset: number
  setOffset: (value: number) => void
  onRetry: () => void
}) {
  const canPrev = offset > 0
  const canNext = offset + PAGE_LIMIT < (total ?? 0)
  return (
    <section className="glass-panel p-4" aria-label="At-risk inventory table">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-foreground">At-risk inventory</h3>
        <span className="text-xs text-muted-foreground">{formatNumber(total ?? 0)} products</span>
      </div>
      {isLoading ? (
        <div className="mt-4 h-48 rounded-lg bg-muted/30" role="status" aria-label="Loading dead-stock products" />
      ) : isError ? (
        <div className="mt-4">
          <ErrorState title="Dead-stock products unavailable" message="We couldn't load the at-risk inventory table." action={<Button variant="outline" size="sm" onClick={onRetry}>Retry</Button>} />
        </div>
      ) : !rows?.length ? (
        <div className="mt-4 rounded-lg border border-dashed border-border/60 bg-muted/30 p-4 text-sm text-muted-foreground">
          No dead-stock products match the selected filters.
        </div>
      ) : (
        <>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[960px] text-left text-sm">
              <thead className="text-xs uppercase text-muted-foreground">
                <tr className="border-b border-border/70">
                  <th className="py-2 pr-3">Product</th>
                  <th className="py-2 pr-3">Current stock</th>
                  <th className="py-2 pr-3">Inventory age</th>
                  <th className="py-2 pr-3">Last sale</th>
                  <th className="py-2 pr-3">Classification</th>
                  <th className="py-2 pr-3">Risk</th>
                  <th className="py-2 pr-3">Locked capital</th>
                  <th className="py-2 pr-3">Recommended action</th>
                  <th className="py-2 pr-3">Potential recovery</th>
                  <th className="py-2">Last calculated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {rows.map((row: DeadStockProduct) => (
                  <tr key={row.productId}>
                    <td className="py-3 pr-3">
                      <div className="font-medium text-foreground">{row.productName}</div>
                      <div className="text-xs text-muted-foreground">{row.category || "Uncategorized"}</div>
                    </td>
                    <td className="py-3 pr-3">{formatNumber(row.currentStock)}</td>
                    <td className="py-3 pr-3">
                      {row.inventoryAgeDays == null ? (
                        <UnavailableValueWithReason
                          label="Inventory age"
                          fallback="Add inventory receipt, lot, goods-received date, or stock-in transaction."
                        />
                      ) : `${formatNumber(row.inventoryAgeDays)} days`}
                      {row.inventoryAgeIsEstimated ? <span className="ml-2 rounded border border-amber-400/40 px-1.5 py-0.5 text-xs text-amber-200">Estimated age</span> : null}
                      <div className="text-xs text-muted-foreground">{labelize(row.ageSource)}</div>
                    </td>
                    <td className="py-3 pr-3">
                      {row.daysSinceLastSale == null ? (
                        <UnavailableValueWithReason
                          label="Last sale"
                          fallback="Import completed or fulfilled sales records, or confirm never sold when supported."
                        />
                      ) : `${row.daysSinceLastSale} days`}
                    </td>
                    <td className="py-3 pr-3">{labelize(row.classification)}</td>
                    <td className="py-3 pr-3">
                      <DeadStockRiskBadge level={row.riskLevel} />
                      <div className="text-xs text-muted-foreground">
                        {row.riskScore == null ? "Risk score requires dead-stock assessment" : `Score ${formatDecimal(row.riskScore)}`}
                      </div>
                    </td>
                    <td className="py-3 pr-3">
                      {row.lockedCapital == null ? (
                        <UnavailableValueWithReason
                          label="Locked capital"
                          fallback="Add product landed cost to calculate locked capital."
                        />
                      ) : currency(row.lockedCapital)}
                    </td>
                    <td className="py-3 pr-3">
                      {row.primaryRecommendation ? labelize(row.primaryRecommendation) : (
                        <UnavailableValueWithReason
                          label="Recommendation"
                          fallback="Add product cost, selling price, marketplace fee policy, and pricing policy."
                        />
                      )}
                    </td>
                    <td className="py-3 pr-3">
                      {row.potentialRecovery == null ? (
                        <UnavailableValueWithReason
                          label="Potential recovery"
                          fallback="Marketplace fees and safe discount validation are required before estimating recovery."
                        />
                      ) : currency(row.potentialRecovery)}
                    </td>
                    <td className="py-3">{formatDateTime(row.lastCalculatedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex items-center justify-between">
            <Button variant="outline" size="sm" disabled={!canPrev} onClick={() => setOffset(Math.max(0, offset - PAGE_LIMIT))}>Previous</Button>
            <span className="text-xs text-muted-foreground">Page {Math.floor(offset / PAGE_LIMIT) + 1}</span>
            <Button variant="outline" size="sm" disabled={!canNext} onClick={() => setOffset(offset + PAGE_LIMIT)}>Next</Button>
          </div>
        </>
      )}
    </section>
  )
}

function AgeDistribution({ data }: { data?: Record<string, number> }) {
  const rows = ["0-30", "31-45", "46-60", "61-90", "91-180", "180+"].map((bucket) => ({
    bucket,
    count: data?.[bucket] ?? 0,
  }))
  return (
    <section className="glass-panel p-4" aria-label="Inventory age distribution">
      <h3 className="text-sm font-semibold text-foreground">Inventory age distribution</h3>
      <div className="mt-4 h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
            <XAxis dataKey="bucket" tickLine={false} axisLine={false} />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
            <Tooltip />
            <Bar dataKey="count" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}

function RecoveryPanel({
  productId,
  intelligence,
  readiness,
}: {
  productId: string
  intelligence?: ProductDeadStockIntelligence
  readiness?: DeadStockReadiness
}) {
  const [discount, setDiscount] = useState("0.10")
  const simulation = useRecoverySimulation(productId || undefined)
  const recommendation = intelligence?.recoveryRecommendation
  const capital = intelligence?.capitalRecovery
  const rejected = (recommendation?.rejected_actions as Array<{ action: string; reasons?: string[] }> | undefined) ?? []
  const costCheck = readiness?.checks.product_cost
  const feeCheck = readiness?.checks.marketplace_fee_policy
  const policyCheck = readiness?.checks.pricing_policy
  const canSimulate = Boolean(productId && readiness?.canEstimatePotentialRecovery)
  const simulationBlocker =
    costCheck?.reasonCode === "MISSING_PRODUCT_COST"
      ? "Product cost is required before recovery simulation."
      : feeCheck?.reasonCode === "MISSING_MARKETPLACE_FEE_POLICY"
        ? "Marketplace fee policy is required before discount recovery can be estimated safely."
        : policyCheck?.reasonCode === "MISSING_PRICING_POLICY"
          ? "Pricing policy is required before MarginGuard can validate recovery pricing."
          : null
  const runSimulation = () => {
    if (!canSimulate) return
    simulation.mutate({
      action: intelligence?.primaryRecoveryRecommendation || "DISCOUNT",
      candidateDiscount: Number(discount),
      eligibleQuantity: intelligence?.eligibleUnsoldQuantity ?? undefined,
    })
  }
  const simulated = simulation.data
  return (
    <section className="glass-panel p-4" aria-label="Recovery recommendation panel">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Recovery recommendation</h3>
          <p className="mt-1 text-xs text-muted-foreground">Recommendations are estimates and do not execute marketplace changes.</p>
        </div>
        <span className="rounded-full border border-border bg-muted/30 px-2 py-1 text-xs font-semibold text-foreground">
          {intelligence?.primaryRecoveryRecommendation ? labelize(intelligence.primaryRecoveryRecommendation) : "Recommendation unavailable"}
        </span>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <Detail label="Suggested discount" value={intelligence?.recommendedDiscountRate == null ? "Unavailable - MarginGuard needs safe pricing data" : `${Math.round(intelligence.recommendedDiscountRate * 100)}%`} />
        <Detail label="Recommended price" value={intelligence?.recommendedPrice == null ? "Unavailable - safe price not calculated" : currency(intelligence.recommendedPrice)} />
        <Detail label="Expected cash range" value={intelligence?.potentialRecoveredCashLow == null || intelligence?.potentialRecoveredCashHigh == null ? "Unavailable - recovery estimate is blocked" : `${currency(intelligence.potentialRecoveredCashLow)} - ${currency(intelligence.potentialRecoveredCashHigh)}`} />
        <Detail label="Confidence" value={formatDecimal(intelligence?.confidence, "%")} />
      </div>
      {recommendation?.explanation ? (
        <div className="mt-3 rounded-lg border border-border/70 bg-muted/20 p-3 text-sm text-muted-foreground">
          {String(recommendation.explanation)}
        </div>
      ) : null}
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">Assumptions</h4>
          <ul className="mt-2 space-y-1 text-sm text-foreground">
            <li>Margin safety: {capital?.estimate_status === "BLOCKED_BY_MARGIN_POLICY" ? "Blocked by MarginGuard" : "Evaluated when pricing data is available"}</li>
            <li>Estimate method: {labelize(String(capital?.estimation_method ?? ""))}</li>
            <li>No automatic price, campaign, title, bundle, stock, or customer action is performed.</li>
          </ul>
        </div>
        <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">Rejected actions</h4>
          {rejected.length ? (
            <ul className="mt-2 space-y-2 text-sm text-foreground">
              {rejected.slice(0, 4).map((item, index) => (
                <li key={`${item.action}-${index}`}>
                  <span className="font-medium">{labelize(item.action)}:</span> {(item.reasons ?? []).join(", ") || "Rejected by rule"}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">No rejected actions were returned.</p>
          )}
        </div>
      </div>
      <div className="mt-4 rounded-lg border border-border/70 bg-muted/20 p-3" aria-label="Capital recovery simulator">
        <h4 className="text-sm font-semibold text-foreground">Capital recovery simulator</h4>
        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Candidate discount
            <select className="h-10 rounded-lg border border-border bg-background px-3 text-sm text-foreground" value={discount} onChange={(event) => setDiscount(event.target.value)}>
              <option value="0.05">5%</option>
              <option value="0.10">10%</option>
              <option value="0.15">15%</option>
              <option value="0.20">20%</option>
            </select>
          </label>
          <Button size="sm" onClick={runSimulation} disabled={!canSimulate || simulation.isPending}>
            {simulation.isPending ? <RefreshCw className="size-4 animate-spin" /> : <Coins className="size-4" />}
            Estimate recovery
          </Button>
        </div>
        {simulationBlocker ? (
          <p className="mt-3 text-sm text-amber-100">{simulationBlocker}</p>
        ) : null}
        {simulation.isError ? (
          <p className="mt-3 text-sm text-red-200">Simulation unavailable. Check cost and marketplace fee setup.</p>
        ) : simulated ? (
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            <Detail label="Locked capital" value={currency(simulated.lockedCapital)} />
            <Detail label="Potential cash" value={currency(simulated.potentialRecoveredCash)} />
            <Detail label="Status" value={labelize(String(simulated.capitalRecovery?.estimate_status ?? ""))} />
          </div>
        ) : null}
      </div>
    </section>
  )
}

function DataQualityPanel({
  intelligence,
  readiness,
}: {
  intelligence?: ProductDeadStockIntelligence
  readiness?: DeadStockReadiness
}) {
  const readinessChecks = Object.entries(readiness?.checks ?? {}).filter(([, check]) => check.reasonCode)
  const blocking = readinessChecks.filter(([, check]) => check.blocking)
  const optional = readinessChecks.filter(([, check]) => !check.blocking && check.status === "UNAVAILABLE")
  const pending = readinessChecks.filter(([, check]) => check.status === "PENDING_CALCULATION" || check.status === "ACTION_REQUIRED")
  const estimated = intelligence?.inventoryAgeIsEstimated
  return (
    <section className="glass-panel p-4" aria-label="Data quality panel">
      <h3 className="text-sm font-semibold text-foreground">Data quality</h3>
      {readinessChecks.length || estimated ? (
        <div className="mt-3 space-y-3">
          <QualityGroup title="Blocking setup required" items={blocking} />
          <QualityGroup title="Optional data unavailable" items={optional} />
          <QualityGroup title="Pending calculations" items={pending} />
          {estimated ? (
            <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 p-3 text-sm">
              <div className="flex items-center gap-2 font-medium text-amber-100"><FileWarning className="size-4" />Estimated age</div>
              <p className="mt-1 text-amber-50/80">Inventory age is estimated from the earliest available stock record.</p>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">No blocking data quality issues were returned.</p>
      )}
    </section>
  )
}

function QualityGroup({
  title,
  items,
}: {
  title: string
  items: Array<[string, DeadStockReadiness["checks"][string]]>
}) {
  if (!items.length) return null
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase text-muted-foreground">{title}</h4>
      <div className="mt-2 space-y-2">
        {items.map(([key, check]) => (
          <div key={key} className="rounded-lg border border-border/70 bg-muted/20 p-3 text-sm">
            <div className="flex items-center gap-2 font-medium text-foreground">
              <FileWarning className="size-4" />
              {labelize(key)}
            </div>
            <p className="mt-1 text-muted-foreground">{check.message}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function InventoryIntelligencePage() {
  const productsQuery = useProducts()
  const products = productsQuery.data ?? []
  const [productId, setProductId] = useState("")
  const [riskLevel, setRiskLevel] = useState<InventoryRiskLevel | "ALL">("ALL")
  const [deadStockClassification, setDeadStockClassification] = useState<DeadStockClassification | "ALL">("ALL")
  const [deadStockRisk, setDeadStockRisk] = useState<DeadStockRiskLevel | "ALL">("ALL")
  const [deadStockDataStatus, setDeadStockDataStatus] = useState<DeadStockDataStatus | "ALL">("ALL")
  const [deadStockAction, setDeadStockAction] = useState<RecoveryAction | "ALL">("ALL")
  const [deadStockSort, setDeadStockSort] = useState<"risk" | "age" | "locked_capital" | "potential_recovery">("risk")
  const [deadStockOffset, setDeadStockOffset] = useState(0)
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
  const deadStockSummary = useDeadStockSummary()
  const deadStockFilters = useMemo(
    () => ({
      classification: deadStockClassification,
      riskLevel: deadStockRisk,
      dataStatus: deadStockDataStatus,
      recommendationAction: deadStockAction,
      sort: deadStockSort,
      limit: PAGE_LIMIT,
      offset: deadStockOffset,
    }),
    [deadStockAction, deadStockClassification, deadStockDataStatus, deadStockOffset, deadStockRisk, deadStockSort]
  )
  const deadStockProducts = useDeadStockProducts(deadStockFilters)
  const reorderList = useInventoryReorderList({
    ...filters,
    sort: "deadline",
  })
  const risks = useInventoryRisks(filters)
  const productIntelligence = useProductInventoryIntelligence(productId || undefined)
  const deadStockIntelligence = useProductDeadStockIntelligence(productId || undefined)
  const deadStockReadiness = useDeadStockReadiness(productId || undefined)
  const deadStockRecalculation = useDeadStockRecalculation(productId || undefined)
  const dailyWorkflow = useRunDailyInventoryWorkflow()
  const productWorkflow = useRunProductInventoryWorkflow()
  const selectedProduct = products.find((product) => product.id === productId)

  const isRefreshing =
    summary.isFetching ||
    reorderList.isFetching ||
    risks.isFetching ||
    productIntelligence.isFetching ||
    deadStockSummary.isFetching ||
    deadStockProducts.isFetching ||
    deadStockIntelligence.isFetching ||
    deadStockReadiness.isFetching

  const refreshAll = () => {
    void summary.refetch()
    void reorderList.refetch()
    void risks.refetch()
    void deadStockSummary.refetch()
    void deadStockProducts.refetch()
    if (productId) {
      void productIntelligence.refetch()
      void deadStockIntelligence.refetch()
      void deadStockReadiness.refetch()
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

      <section className="space-y-4" aria-label="Dead stock dashboard">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-foreground">Dead stock recovery</h2>
            <p className="text-sm text-muted-foreground">
              Estimated locked capital and recovery recommendations. Values are estimates, not guaranteed cash.
            </p>
          </div>
          <span className="text-xs text-muted-foreground">
            Formula {deadStockSummary.data?.formulaVersion ?? "not available"}
          </span>
        </div>
        {deadStockSummary.isError && !deadStockSummary.data ? (
          <ErrorState
            title="Dead-stock summary unavailable"
            message="We couldn't load the Phase 9 summary."
            action={<Button variant="outline" size="sm" onClick={() => deadStockSummary.refetch()}>Retry</Button>}
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <MetricCard label="Dead-stock products" value={formatNumber(deadStockSummary.data?.deadStockCount ?? 0)} helper={`${formatNumber(deadStockSummary.data?.totalEligibleDeadStockUnits ?? 0)} eligible units`} icon={PackageSearch} />
            <MetricCard label="At-risk products" value={formatNumber(deadStockSummary.data?.atRiskCount ?? 0)} helper={`${formatNumber(deadStockSummary.data?.slowMovingCount ?? 0)} slow-moving products`} icon={ShieldAlert} />
            <MetricCard label="Locked capital" value={currency(deadStockSummary.data?.totalLockedCapital)} helper={deadStockSummary.data?.lockedCapitalCurrency ?? "Currency unavailable"} icon={Coins} />
            <MetricCard label="Potential recoverable cash" value={currency(deadStockSummary.data?.estimatedRecoverableCash)} helper={deadStockSummary.data?.monetaryTotalsComparable ? `Comparable ${deadStockSummary.data.forecastHorizonDays ?? ""} day horizon` : "Estimate not aggregated across mixed currency or horizons"} icon={Truck} />
            <MetricCard label="Manual review" value={formatNumber(deadStockSummary.data?.productsRequiringManualReview ?? 0)} helper={`${formatNumber(deadStockSummary.data?.productsWithInsufficientData ?? 0)} products with insufficient data`} icon={AlertTriangle} />
          </div>
        )}
        <div className="glass-panel flex flex-col gap-3 p-4 lg:flex-row lg:flex-wrap lg:items-end">
          <SelectFilter label="Classification" value={deadStockClassification} onChange={(value) => { setDeadStockClassification(value); setDeadStockOffset(0) }} options={[
            { value: "ALL", label: "All classifications" },
            { value: "SLOW_MOVING", label: "Slow moving" },
            { value: "AT_RISK", label: "At risk" },
            { value: "DEAD_STOCK", label: "Dead stock" },
            { value: "HEALTHY", label: "Healthy" },
            { value: "INSUFFICIENT_DATA", label: "Insufficient data" },
          ]} />
          <SelectFilter label="Risk" value={deadStockRisk} onChange={(value) => { setDeadStockRisk(value); setDeadStockOffset(0) }} options={[
            { value: "ALL", label: "All risks" },
            { value: "CRITICAL", label: "Critical" },
            { value: "HIGH", label: "High" },
            { value: "MEDIUM", label: "Medium" },
            { value: "LOW", label: "Low" },
          ]} />
          <SelectFilter label="Action" value={deadStockAction} onChange={(value) => { setDeadStockAction(value); setDeadStockOffset(0) }} options={[
            { value: "ALL", label: "All actions" },
            { value: "BUNDLE", label: "Bundle" },
            { value: "DISCOUNT", label: "Discount" },
            { value: "FLASH_SALE", label: "Flash sale" },
            { value: "SEO_FIX", label: "SEO fix" },
            { value: "HOLD", label: "Hold" },
            { value: "MANUAL_REVIEW", label: "Manual review" },
          ]} />
          <SelectFilter label="Data status" value={deadStockDataStatus} onChange={(value) => { setDeadStockDataStatus(value); setDeadStockOffset(0) }} options={[
            { value: "ALL", label: "All data statuses" },
            { value: "SUFFICIENT", label: "Sufficient" },
            { value: "LIMITED", label: "Limited" },
            { value: "INSUFFICIENT", label: "Insufficient" },
          ]} />
          <SelectFilter label="Sort" value={deadStockSort} onChange={(value) => { setDeadStockSort(value); setDeadStockOffset(0) }} options={[
            { value: "risk", label: "Risk" },
            { value: "age", label: "Age" },
            { value: "locked_capital", label: "Locked capital" },
            { value: "potential_recovery", label: "Potential recovery" },
          ]} />
        </div>
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.75fr)]">
          <DeadStockTable
            rows={deadStockProducts.data?.items}
            total={deadStockProducts.data?.total}
            isLoading={deadStockProducts.isLoading}
            isError={deadStockProducts.isError}
            offset={deadStockOffset}
            setOffset={setDeadStockOffset}
            onRetry={() => deadStockProducts.refetch()}
          />
          <AgeDistribution data={deadStockSummary.data?.ageDistribution} />
        </div>
        {productId ? (
          <DeadStockReadinessPanel
            readiness={deadStockReadiness.data}
            isError={deadStockReadiness.isError}
            onRunAnalysis={() => deadStockRecalculation.mutate()}
            runAnalysisPending={deadStockRecalculation.isPending}
          />
        ) : null}
        <div className="grid gap-4 xl:grid-cols-2">
          <RecoveryPanel productId={productId} intelligence={deadStockIntelligence.data} readiness={deadStockReadiness.data} />
          <DataQualityPanel intelligence={deadStockIntelligence.data} readiness={deadStockReadiness.data} />
        </div>
        <div className="glass-panel p-4" aria-label="Triggered rules and evidence">
          <h3 className="text-sm font-semibold text-foreground">Triggered rules and evidence</h3>
          {!productId ? (
            <p className="mt-3 text-sm text-muted-foreground">Select a product to review dead-stock rules, recovery evidence, and recommendation history.</p>
          ) : deadStockIntelligence.isLoading ? (
            <div className="mt-3 h-20 rounded-lg bg-muted/30" />
          ) : deadStockIntelligence.isError ? (
            <p className="mt-3 text-sm text-red-200">Product dead-stock intelligence is unavailable.</p>
          ) : (
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                <h4 className="text-xs font-semibold uppercase text-muted-foreground">Triggered rules</h4>
                {deadStockIntelligence.data?.triggeredRules.length ? (
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {deadStockIntelligence.data.triggeredRules.map((rule: string) => (
                      <li key={rule} className="rounded-full border border-border bg-background px-2 py-1 text-xs text-foreground">{labelize(rule)}</li>
                    ))}
                  </ul>
                ) : <p className="mt-2 text-sm text-muted-foreground">No triggered rules returned.</p>}
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                <h4 className="text-xs font-semibold uppercase text-muted-foreground">Recommendation history</h4>
                <p className="mt-2 text-sm text-foreground">Latest action: {labelize(deadStockIntelligence.data?.primaryRecoveryRecommendation)}</p>
                <p className="text-sm text-muted-foreground">Last updated: {formatDateTime(deadStockIntelligence.data?.lastUpdatedAt)}</p>
              </div>
            </div>
          )}
        </div>
      </section>

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
