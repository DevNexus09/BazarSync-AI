import { useMemo, useState, type ReactNode } from "react"
import {
  AlertTriangle,
  BadgeDollarSign,
  Check,
  CircleCheck,
  PackageCheck,
  PackageX,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  UserMinus,
  UserPlus,
  X,
} from "lucide-react"

import { ErrorState } from "@/components/common/error-state"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/use-auth"
import { useProducts } from "@/hooks/use-products"
import {
  useOpportunityActions,
  usePhase5MarketPosition,
  usePhase5Opportunities,
  usePhase5PriceChanges,
  usePhase5Summary,
} from "@/hooks/usePhase5Dashboard"
import { usePhase5RealtimeInvalidation } from "@/hooks/usePhase5RealtimeInvalidation"
import { cn } from "@/lib/utils"
import {
  CompetitorEventType,
  EventSeverity,
  OpportunityLevel,
  type CompetitorActivity,
  type LatestPriceChange,
  type MarketPositionCard,
  type OpportunityFeedItem,
  type PageResponse,
  type Phase5DashboardFilters,
  type Phase5Summary,
} from "@/types/phase5-dashboard"
import type { Product } from "@/types/product"
import {
  formatDateTime,
  formatNumber,
  formatOptionalCurrency,
  formatOptionalPercent,
} from "@/utils/formatters"

const PAGE_LIMIT = 5

const eventLabels: Record<CompetitorEventType, string> = {
  PRICE_DROP: "Price drop",
  PRICE_RISE: "Price rise",
  OUT_OF_STOCK: "Out of stock",
  BACK_IN_STOCK: "Back in stock",
  NEW_COMPETITOR: "New competitor",
  COMPETITOR_REMOVED: "Competitor removed",
}

const eventIcons = {
  PRICE_DROP: TrendingDown,
  PRICE_RISE: TrendingUp,
  OUT_OF_STOCK: PackageX,
  BACK_IN_STOCK: PackageCheck,
  NEW_COMPETITOR: UserPlus,
  COMPETITOR_REMOVED: UserMinus,
} satisfies Record<CompetitorEventType, typeof TrendingDown>

const eventBadgeStyles: Record<CompetitorEventType, string> = {
  PRICE_DROP: "border-emerald-400/40 bg-emerald-400/10 text-success",
  PRICE_RISE: "border-amber-400/40 bg-amber-400/10 text-warning",
  OUT_OF_STOCK: "border-red-400/40 bg-red-400/10 text-danger",
  BACK_IN_STOCK: "border-cyan-400/40 bg-cyan-400/10 text-info",
  NEW_COMPETITOR: "border-info/40 bg-info/10 text-info",
  COMPETITOR_REMOVED: "border-border-strong/40 bg-muted/60 text-muted-foreground",
}

const severityStyles: Record<EventSeverity, string> = {
  LOW: "border-border-strong/40 bg-muted/60 text-muted-foreground",
  MEDIUM: "border-info/40 bg-info/10 text-info",
  HIGH: "border-warning/40 bg-warning/10 text-warning",
  CRITICAL: "border-danger/40 bg-danger/10 text-danger",
}

const levelStyles: Record<OpportunityLevel, string> = {
  LOW: "border-border-strong/40 bg-muted/60 text-muted-foreground",
  MEDIUM: "border-warning/40 bg-warning/10 text-warning",
  HIGH: "border-danger/40 bg-danger/10 text-danger",
}

export function Phase5Dashboard() {
  const { user } = useAuth()
  const productsQuery = useProducts()
  const products = productsQuery.data ?? []
  const [productId, setProductId] = useState<string>("")
  const [windowHours, setWindowHours] = useState(24)
  const [opportunityLevel, setOpportunityLevel] =
    useState<Phase5DashboardFilters["opportunityLevel"]>("ALL")
  const [priceOffset, setPriceOffset] = useState(0)
  const [opportunityOffset, setOpportunityOffset] = useState(0)

  const filters = useMemo<Phase5DashboardFilters>(
    () => ({
      productId: productId || undefined,
      windowHours,
      opportunityLevel,
    }),
    [opportunityLevel, productId, windowHours]
  )

  const summary = usePhase5Summary(filters)
  const marketPosition = usePhase5MarketPosition(filters.productId)
  const priceChanges = usePhase5PriceChanges(filters, {
    limit: PAGE_LIMIT,
    offset: priceOffset,
  })
  const opportunities = usePhase5Opportunities(filters, {
    limit: PAGE_LIMIT,
    offset: opportunityOffset,
  })

  usePhase5RealtimeInvalidation({
    sellerId: user?.id,
    productId: filters.productId,
    accessibleProductIds: products.map((product) => product.id),
    enabled: Boolean(user?.id),
  })

  const selectedProduct = products.find((product) => product.id === productId)
  const isRefreshing =
    summary.isFetching ||
    priceChanges.isFetching ||
    opportunities.isFetching ||
    marketPosition.isFetching

  return (
    <section className="space-y-4" aria-labelledby="phase5-dashboard-heading">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2
            id="phase5-dashboard-heading"
            className="heading-font text-2xl font-semibold text-foreground"
          >
            Competitor intelligence
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Recent event counts use the selected time window. Competitor count
            uses the latest completed scrape run.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void summary.refetch()
            void priceChanges.refetch()
            void opportunities.refetch()
            void marketPosition.refetch()
          }}
        >
          <RefreshCw className={cn("size-4", isRefreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>

      <Filters
        products={products}
        productId={productId}
        setProductId={(value) => {
          setProductId(value)
          setPriceOffset(0)
          setOpportunityOffset(0)
        }}
        windowHours={windowHours}
        setWindowHours={(value) => {
          setWindowHours(value)
          setPriceOffset(0)
        }}
        opportunityLevel={opportunityLevel}
        setOpportunityLevel={(value) => {
          setOpportunityLevel(value)
          setOpportunityOffset(0)
        }}
      />

      <SummaryMetrics
        summary={summary.data}
        isLoading={summary.isLoading}
        isError={summary.isError}
        onRetry={() => summary.refetch()}
      />

      <div className="grid gap-4 2xl:grid-cols-12">
        <div className="2xl:col-span-7">
          <LatestPriceChanges
            data={priceChanges.data}
            isLoading={priceChanges.isLoading}
            isError={priceChanges.isError}
            onRetry={() => priceChanges.refetch()}
            offset={priceOffset}
            setOffset={setPriceOffset}
          />
        </div>
        <div className="2xl:col-span-5">
          <MarketPosition
            product={selectedProduct}
            data={marketPosition.data}
            isLoading={marketPosition.isLoading}
            isError={marketPosition.isError}
            onRetry={() => marketPosition.refetch()}
          />
        </div>
        <div className="2xl:col-span-12">
          <OpportunityFeed
            data={opportunities.data}
            isLoading={opportunities.isLoading}
            isError={opportunities.isError}
            onRetry={() => opportunities.refetch()}
            offset={opportunityOffset}
            setOffset={setOpportunityOffset}
          />
        </div>
      </div>
    </section>
  )
}

type FilterProps = {
  products: Product[]
  productId: string
  setProductId: (value: string) => void
  windowHours: number
  setWindowHours: (value: number) => void
  opportunityLevel: Phase5DashboardFilters["opportunityLevel"]
  setOpportunityLevel: (value: Phase5DashboardFilters["opportunityLevel"]) => void
}

function Filters({
  products,
  productId,
  setProductId,
  windowHours,
  setWindowHours,
  opportunityLevel,
  setOpportunityLevel,
}: FilterProps) {
  const selectClass =
    "h-10 w-full rounded-lg border border-border/70 bg-background/70 px-3 text-sm font-medium text-foreground outline-none transition focus-visible:border-primary/70 focus-visible:ring-2 focus-visible:ring-primary/30"
  const labelClass =
    "flex min-w-0 flex-col gap-1.5 text-xs font-medium text-muted-foreground"

  return (
    <div className="rounded-xl border border-border/60 bg-card/45 p-3 shadow-sm">
      <div className="flex flex-col gap-3 md:flex-row md:items-end">
        <label className={cn(labelClass, "md:w-[340px]")}>
        <span>Product</span>
        <select
          className={selectClass}
          value={productId}
          onChange={(event) => setProductId(event.target.value)}
        >
          <option value="">All products</option>
          {products.map((product) => (
            <option key={product.id} value={product.id}>
              {product.title}
            </option>
          ))}
        </select>
      </label>
        <label className={cn(labelClass, "md:w-[180px]")}>
        <span>Recent window</span>
        <select
          className={selectClass}
          value={windowHours}
          onChange={(event) => setWindowHours(Number(event.target.value))}
        >
          <option value={24}>Last 24 hours</option>
          <option value={48}>Last 48 hours</option>
          <option value={72}>Last 72 hours</option>
          <option value={168}>Last 7 days</option>
        </select>
      </label>
        <label className={cn(labelClass, "md:w-[180px]")}>
        <span>Opportunity level</span>
        <select
          className={selectClass}
          value={opportunityLevel}
          onChange={(event) =>
            setOpportunityLevel(
              event.target.value as Phase5DashboardFilters["opportunityLevel"]
            )
          }
        >
          <option value="ALL">All levels</option>
          {Object.values(OpportunityLevel).map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </label>
      </div>
    </div>
  )
}

export function SummaryMetrics({
  summary,
  isLoading,
  isError,
  onRetry,
}: {
  summary?: Phase5Summary
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}) {
  if (isError && !summary) {
    return (
      <ErrorState
        title="Phase 5 summary unavailable"
        message="We couldn't load competitor intelligence metrics."
        action={
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        }
      />
    )
  }
  const metrics = [
    ["Active competitors", summary?.competitorCount, "latest completed run"],
    ["Recent price drops", summary?.priceDropCount, `${summary?.windowHours ?? 24}h window`],
    ["Recent stockouts", summary?.stockoutCount, `${summary?.windowHours ?? 24}h window`],
    ["Open opportunities", summary?.openOpportunityCount, "currently open"],
  ] as const

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      {metrics.map(([label, value, scope]) => (
        <div key={label} className="glass-panel p-4">
          <div className="text-xs text-muted-foreground">{label}</div>
          <div className="mt-2 text-2xl font-semibold text-foreground">
            {isLoading ? <SkeletonText className="h-8 w-20" /> : formatNumber(value ?? 0)}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">{scope}</div>
        </div>
      ))}
      <div className="glass-panel p-4 sm:col-span-2 xl:col-span-1">
        <div className="text-xs text-muted-foreground">Last updated</div>
        <div className="mt-2 text-sm font-semibold text-foreground">
          {isLoading ? (
            <SkeletonText className="h-5 w-32" />
          ) : (
            formatDateTime(summary?.lastUpdatedAt)
          )}
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          Window: {summary?.windowHours ?? 24} hours
        </div>
      </div>
    </div>
  )
}

export function LatestPriceChanges({
  data,
  isLoading,
  isError,
  onRetry,
  offset,
  setOffset,
}: FeedProps<LatestPriceChange>) {
  return (
    <Panel
      title="Latest price changes"
      count={data?.total}
      isError={isError}
      errorTitle="Price changes unavailable"
      onRetry={onRetry}
    >
      {isLoading ? (
        <ListSkeleton rows={4} />
      ) : data && data.items.length > 0 ? (
        <div className="space-y-3">
          {data.items.map((item) => (
            <div
              key={item.id}
              className="rounded-xl border border-border/60 bg-muted/20 p-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-foreground">
                    {item.competitor ?? "Unknown competitor"}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    {item.product ?? "Unknown product"}
                  </div>
                </div>
                <EventBadge type={item.eventType} />
              </div>
              <div className="mt-3 grid gap-2 text-xs sm:grid-cols-4">
                <Value label="Previous" value={formatOptionalCurrency(item.oldPrice)} />
                <Value label="Current" value={formatOptionalCurrency(item.newPrice)} />
                <Value label="Changed" value={formatOptionalCurrency(item.changeAmount)} />
                <Value
                  label="Percent"
                  value={formatOptionalPercent(item.changePercentage)}
                />
              </div>
              <div className="mt-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <SeverityBadge severity={item.severity} />
                <time dateTime={item.eventTime}>{formatDateTime(item.eventTime)}</time>
              </div>
            </div>
          ))}
          <Pagination data={data} offset={offset} setOffset={setOffset} />
        </div>
      ) : (
        <EmptyState message="No price drops or rises in this window." />
      )}
    </Panel>
  )
}

export function ActivityFeed({
  data,
  isLoading,
  isError,
  onRetry,
  offset,
  setOffset,
}: FeedProps<CompetitorActivity>) {
  return (
    <Panel
      title="Competitor activity feed"
      count={data?.total}
      isError={isError}
      errorTitle="Activity unavailable"
      onRetry={onRetry}
    >
      {isLoading ? (
        <ListSkeleton rows={5} />
      ) : data && data.items.length > 0 ? (
        <div className="space-y-3">
          {data.items.map((item) => {
            const Icon = eventIcons[item.eventType]
            return (
              <div
                key={item.id}
                className="flex gap-3 rounded-xl border border-border/60 bg-muted/20 p-3"
              >
                <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-card/70">
                  <Icon className="size-4" aria-hidden="true" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <EventBadge type={item.eventType} />
                    <SeverityBadge severity={item.severity} />
                  </div>
                  <div className="mt-2 text-sm font-semibold text-foreground">
                    {item.competitor ?? "Unknown competitor"}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {item.product ?? "Unknown product"}
                  </div>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {item.description}
                  </p>
                  <time
                    className="mt-2 block text-xs text-muted-foreground"
                    dateTime={item.eventTime}
                  >
                    {formatDateTime(item.eventTime)}
                  </time>
                </div>
              </div>
            )
          })}
          <Pagination data={data} offset={offset} setOffset={setOffset} />
        </div>
      ) : (
        <EmptyState message="No competitor events match the current filters." />
      )}
    </Panel>
  )
}

export function OpportunityFeed({
  data,
  isLoading,
  isError,
  onRetry,
  offset,
  setOffset,
}: FeedProps<OpportunityFeedItem>) {
  const actions = useOpportunityActions()
  return (
    <Panel
      title="Opportunity feed"
      count={data?.total}
      isError={isError}
      errorTitle="Opportunities unavailable"
      onRetry={onRetry}
    >
      {isLoading ? (
        <ListSkeleton rows={4} />
      ) : data && data.items.length > 0 ? (
        <div className="space-y-3">
          {data.items.map((item) => (
            <div
              key={item.id}
              className="rounded-xl border border-border/60 bg-muted/20 p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-semibold",
                    levelStyles[item.opportunityLevel]
                  )}
                >
                  <AlertTriangle className="size-3" aria-hidden="true" />
                  {item.opportunityLevel}
                </span>
                <span className="text-xs text-muted-foreground">
                  Score {Math.round(item.opportunityScore)}
                </span>
              </div>
              <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
                <Value
                  label="Estimated revenue"
                  value={
                    item.estimatedRevenueState === "insufficient_data"
                      ? "Insufficient sales history"
                      : formatOptionalCurrency(item.estimatedRevenue)
                  }
                />
                <Value label="Action" value={formatAction(item.recommendedAction)} />
                <Value
                  label="Confidence"
                  value={`${Math.round(item.confidenceScore)}%`}
                />
              </div>
              <p className="mt-3 text-sm text-muted-foreground">
                {item.explanation}
              </p>
              <p className="mt-2 text-xs text-muted-foreground">
                Evidence: {item.evidenceSummary}
              </p>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                <time className="text-xs text-muted-foreground" dateTime={item.detectedAt}>
                  {formatDateTime(item.detectedAt)}
                </time>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="xs"
                    onClick={() => actions.acknowledge.mutate(item.id)}
                    disabled={actions.acknowledge.isPending}
                  >
                    <Check className="size-3" />
                    Acknowledge
                  </Button>
                  <Button
                    variant="destructive"
                    size="xs"
                    onClick={() => {
                      if (window.confirm("Dismiss this market opportunity?")) {
                        actions.dismiss.mutate(item.id)
                      }
                    }}
                    disabled={actions.dismiss.isPending}
                  >
                    <X className="size-3" />
                    Dismiss
                  </Button>
                </div>
              </div>
            </div>
          ))}
          <Pagination data={data} offset={offset} setOffset={setOffset} />
        </div>
      ) : (
        <EmptyState message="No open market opportunities match the current filters." />
      )}
    </Panel>
  )
}

export function MarketPosition({
  product,
  data,
  isLoading,
  isError,
  onRetry,
}: {
  product?: Product
  data?: MarketPositionCard
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}) {
  return (
    <Panel
      title="Market position card"
      isError={isError}
      errorTitle="Market position unavailable"
      onRetry={onRetry}
    >
      {!product ? (
        <EmptyState message="Select a product to view its market position." />
      ) : isLoading ? (
        <ListSkeleton rows={5} />
      ) : data ? (
        <div className="space-y-3">
          <div className="flex items-start gap-3 rounded-xl border border-border/60 bg-muted/20 p-3">
            <BadgeDollarSign className="mt-0.5 size-5 text-primary" aria-hidden="true" />
            <div>
              <div className="text-sm font-semibold text-foreground">
                {product.title}
              </div>
              <div className="text-xs text-muted-foreground">
                Seller price position relative to market median
              </div>
            </div>
          </div>
          <div className="grid gap-2 text-xs sm:grid-cols-2">
            <Value label="Seller price" value={formatOptionalCurrency(data.sellerProductPrice)} />
            <Value label="Market minimum" value={formatOptionalCurrency(data.lowestCompetitorPrice)} />
            <Value label="Market median" value={formatOptionalCurrency(data.medianCompetitorPrice)} />
            <Value label="Market maximum" value={formatOptionalCurrency(data.highestCompetitorPrice)} />
            <Value label="Strongest competitor" value={data.strongestCompetitorId ?? "Not available"} />
            <Value label="Active competitors" value={formatNumber(data.totalActiveCompetitors)} />
            <Value label="Currently in stock" value={formatNumber(data.totalInStockCompetitors)} />
            <Value
              label="Difference from median"
              value={formatOptionalCurrency(data.sellerPriceDifferenceFromMarketMedian)}
            />
          </div>
          {typeof data.sellerPriceRank === "number" ? (
            <div className="rounded-xl border border-border/60 bg-muted/20 p-3 text-xs text-muted-foreground">
              Seller price rank:{" "}
              <span className="font-semibold text-foreground">
                {formatNumber(data.sellerPriceRank)}
              </span>
            </div>
          ) : null}
          <div className="text-xs text-muted-foreground">
            Last calculated: {formatDateTime(data.rankingLastUpdatedAt)}
          </div>
        </div>
      ) : (
        <EmptyState message="No ranking data has been calculated for this product." />
      )}
    </Panel>
  )
}

type FeedProps<T> = {
  data?: PageResponse<T>
  isLoading: boolean
  isError: boolean
  onRetry: () => void
  offset: number
  setOffset: (value: number) => void
}

function Panel({
  title,
  count,
  isError,
  errorTitle,
  onRetry,
  children,
}: {
  title: string
  count?: number
  isError: boolean
  errorTitle: string
  onRetry: () => void
  children: ReactNode
}) {
  return (
    <div className="glass-panel p-4">
      <div className="mb-4 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        {typeof count === "number" ? (
          <span className="text-xs text-muted-foreground">{formatNumber(count)} total</span>
        ) : null}
      </div>
      {isError ? (
        <ErrorState
          title={errorTitle}
          message="Try again or wait for the next completed scrape run."
          action={
            <Button variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          }
        />
      ) : (
        children
      )}
    </div>
  )
}

function EventBadge({ type }: { type: CompetitorEventType }) {
  const Icon = eventIcons[type]
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-semibold",
        eventBadgeStyles[type]
      )}
    >
      <Icon className="size-3" aria-hidden="true" />
      {eventLabels[type]}
    </span>
  )
}

function SeverityBadge({ severity }: { severity: EventSeverity }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-semibold",
        severityStyles[severity]
      )}
    >
      <CircleCheck className="size-3" aria-hidden="true" />
      {severity}
    </span>
  )
}

function Value({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-card/50 p-2">
      <div className="text-muted-foreground">{label}</div>
      <div className="mt-1 break-words font-semibold text-foreground">{value}</div>
    </div>
  )
}

function Pagination<T>({
  data,
  offset,
  setOffset,
}: {
  data: PageResponse<T>
  offset: number
  setOffset: (value: number) => void
}) {
  const hasPrevious = offset > 0
  const hasNext = offset + data.limit < data.total
  return (
    <div className="flex items-center justify-between gap-3 pt-1">
      <span className="text-xs text-muted-foreground">
        Showing {data.total === 0 ? 0 : offset + 1}-
        {Math.min(offset + data.limit, data.total)} of {data.total}
      </span>
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="xs"
          onClick={() => setOffset(Math.max(offset - data.limit, 0))}
          disabled={!hasPrevious}
        >
          Previous
        </Button>
        <Button
          variant="outline"
          size="xs"
          onClick={() => setOffset(offset + data.limit)}
          disabled={!hasNext}
        >
          Next
        </Button>
      </div>
    </div>
  )
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-dashed border-border/60 bg-muted/20 p-4 text-sm text-muted-foreground">
      {message}
    </div>
  )
}

function ListSkeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-3" role="status" aria-live="polite">
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={`phase5-skeleton-${index}`}
          className="h-24 rounded-xl bg-muted/30"
        />
      ))}
      <span className="sr-only">Loading Phase 5 dashboard data</span>
    </div>
  )
}

function SkeletonText({ className }: { className: string }) {
  return <span className={cn("block rounded bg-muted/40", className)} />
}

function formatAction(action: string) {
  return action
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}
