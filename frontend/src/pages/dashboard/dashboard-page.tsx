import { useMemo } from "react"
import { Link } from "react-router-dom"

import { ErrorState } from "@/components/common/error-state"
import { DashboardSummaryHeader } from "@/components/dashboard/dashboard-summary-header"
import { UrgencyScoreWidget } from "@/components/dashboard/urgency-score-widget"
import { OpportunityMetricsPanel } from "@/components/dashboard/opportunity-metrics-panel"
import { CompetitorPriceChart } from "@/components/dashboard/competitor-price-chart"
import { MarketTrendWidget } from "@/components/dashboard/market-trend-widget"
import { MarketOpportunityCard } from "@/components/dashboard/market-opportunity-card"
import { RealtimeActivityFeed } from "@/components/dashboard/realtime-feed"
import { StockAlertCard } from "@/components/dashboard/stock-alert-card"
import { CompetitorTable } from "@/components/dashboard/competitor-table"
import { CompetitorHeatmap } from "@/components/dashboard/competitor-heatmap"
import { Button } from "@/components/ui/button"
import { useAlerts } from "@/hooks/useAlerts"
import { useCompetitors } from "@/hooks/useCompetitors"
import { useDashboard } from "@/hooks/useDashboard"
import { useProducts } from "@/hooks/use-products"
import { cn } from "@/lib/utils"
import type { Product } from "@/types/product"
import { formatNumber, formatPercent } from "@/utils/formatters"

const LOW_STOCK_THRESHOLD = 10

function getActualMargin(product: Product) {
  if (product.sellingPrice <= 0) {
    return 0
  }

  return ((product.sellingPrice - product.costPrice) / product.sellingPrice) * 100
}

export default function DashboardPage() {
  const queryKey = useDashboard()
  const {
    summary,
    marketTrends,
    opportunityMetrics,
    marketOpportunities,
    activity,
    competitorPriceTrend,
  } = queryKey
  const competitors = useCompetitors()
  const { activeAlerts } = useAlerts()
  const productsQuery = useProducts()

  const isRefreshing =
    summary.isFetching ||
    marketTrends.isFetching ||
    opportunityMetrics.isFetching ||
    marketOpportunities.isFetching ||
    activity.isFetching ||
    competitorPriceTrend.isFetching ||
    competitors.isFetching ||
    activeAlerts.isFetching

  const topOpportunities = useMemo(
    () => (marketOpportunities.data ?? []).slice(0, 3),
    [marketOpportunities.data]
  )
  const products = productsQuery.data ?? []
  const lowStockCount = products.filter(
    (product) => product.stockQuantity <= LOW_STOCK_THRESHOLD
  ).length
  const averageMargin =
    products.length === 0
      ? 0
      : products.reduce((sum, product) => sum + getActualMargin(product), 0) /
        products.length

  return (
    <div className="space-y-6">
<<<<<<< HEAD
      {summary.isError && !summary.data ? (
        <ErrorState
          title="AI Operations Center unavailable"
          message="We couldn't load the AI operations dashboard."
          action={
            <Button variant="outline" size="sm" onClick={() => summary.refetch()}>
              Retry
=======
      <PageHeader
        title="Product command center"
        description="Monitor products feeding competitor scraping, AI pricing, and Telegram alerts."
        action={
          <Button size="sm" asChild>
            <Link to="/app/products/new">Add product</Link>
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border bg-background p-4 shadow-sm">
          <p className="text-sm text-muted-foreground">Total products</p>
          <div className="mt-2 text-2xl font-semibold text-foreground">
            {formatNumber(totalProducts)}
          </div>
        </div>
        <div className="rounded-xl border bg-background p-4 shadow-sm">
          <p className="text-sm text-muted-foreground">Low stock items</p>
          <div className="mt-2 text-2xl font-semibold text-foreground">
            {formatNumber(lowStockCount)}
          </div>
        </div>
        <div className="rounded-xl border bg-background p-4 shadow-sm">
          <p className="text-sm text-muted-foreground">Average margin</p>
          <div className="mt-2 text-2xl font-semibold text-foreground">
            {formatPercent(averageMargin)}
          </div>
        </div>
        <div className="rounded-xl border bg-background p-4 shadow-sm">
          <p className="text-sm text-muted-foreground">Potential profit</p>
          <div className="mt-2 text-2xl font-semibold text-foreground">
            {formatCurrency(potentialProfit)}
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <div className="rounded-xl border bg-background p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-foreground">
              Products needing attention
            </h3>
            {isFetching ? (
              <span className="text-xs text-muted-foreground">Updating...</span>
            ) : null}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Low stock or margin risks that could impact pricing alerts.
          </p>
          {attentionList.length === 0 ? (
            <div className="mt-4 rounded-lg border border-dashed bg-muted/40 p-4 text-sm text-muted-foreground">
              All products are healthy. You’re ready for competitor scraping.
            </div>
          ) : (
            <div className="mt-4 space-y-3">
              {attentionList.map((product) => {
                const actualMargin = getActualMargin(product)
                const isLowStock =
                  product.stockQuantity <= LOW_STOCK_THRESHOLD
                const isBelowMargin = actualMargin < product.minimumMargin
                return (
                  <div
                    key={product.id}
                    className="rounded-lg border border-dashed bg-muted/40 p-3"
                  >
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-semibold text-foreground">
                        {product.title}
                      </p>
                      <span
                        className={cn(
                          "text-xs font-semibold",
                          isBelowMargin ? "text-rose-600" : "text-emerald-600"
                        )}
                      >
                        {formatPercent(actualMargin)}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {isLowStock
                        ? `Stock at ${formatNumber(product.stockQuantity)} units.`
                        : "Margin below minimum threshold."}
                    </p>
                  </div>
                )
              })}
            </div>
          )}
        </div>
        <div className="rounded-xl border bg-background p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-foreground">
              Recently added
            </h3>
            <Button variant="outline" size="sm" asChild>
              <Link to="/app/products">View all</Link>
>>>>>>> develop
            </Button>
          }
        />
      ) : (
        <DashboardSummaryHeader
          summary={summary.data}
          isLoading={summary.isLoading}
          isRefreshing={isRefreshing}
          onRefresh={() => queryKey.summary.refetch()}
        />
      )}

      <div className="grid gap-6 xl:grid-cols-12">
        <div className="xl:col-span-3">
          <UrgencyScoreWidget
            score={summary.data?.urgencyScore}
            isLoading={summary.isLoading}
          />
        </div>
        <div className="xl:col-span-5">
          <OpportunityMetricsPanel
            metrics={opportunityMetrics.data}
            isLoading={opportunityMetrics.isLoading}
          />
        </div>
        <div className="xl:col-span-4">
          <RealtimeActivityFeed
            items={activity.data}
            isLoading={activity.isLoading}
            isError={activity.isError}
            onRetry={() => activity.refetch()}
          />
        </div>

        <div className="xl:col-span-7">
          <CompetitorPriceChart
            data={competitorPriceTrend.data}
            isLoading={competitorPriceTrend.isLoading}
            isError={competitorPriceTrend.isError}
            onRetry={() => competitorPriceTrend.refetch()}
          />
        </div>
        <div className="xl:col-span-5">
          <MarketTrendWidget
            data={marketTrends.data}
            isLoading={marketTrends.isLoading}
            isError={marketTrends.isError}
            onRetry={() => marketTrends.refetch()}
          />
        </div>

        <div className="xl:col-span-7">
          <CompetitorHeatmap
            competitors={competitors.data}
            isLoading={competitors.isLoading}
            isError={competitors.isError}
            onRetry={() => competitors.refetch()}
          />
        </div>
        <div className="xl:col-span-5">
          <div className="glass-panel p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-foreground">
                Market opportunities
              </h3>
              <span className="text-xs text-muted-foreground">
                {marketOpportunities.data?.length ?? 0} total
              </span>
            </div>
            {marketOpportunities.isLoading ? (
              <div className="mt-4 space-y-3">
                {Array.from({ length: 3 }).map((_, index) => (
                  <div
                    key={`opportunity-skeleton-${index}`}
                    className="h-24 rounded-lg bg-muted/30"
                  />
                ))}
              </div>
            ) : marketOpportunities.isError ? (
              <div className="mt-4">
                <ErrorState
                  title="Opportunities unavailable"
                  message="We couldn't load market opportunities."
                  action={
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => marketOpportunities.refetch()}
                    >
                      Retry
                    </Button>
                  }
                />
              </div>
            ) : topOpportunities.length === 0 ? (
              <div className="mt-4 rounded-lg border border-dashed border-border/60 bg-muted/30 p-4 text-xs text-muted-foreground">
                No live opportunities detected yet.
              </div>
            ) : (
              <div className="mt-4 space-y-3">
                {topOpportunities.map((opportunity) => (
                  <MarketOpportunityCard
                    key={opportunity.id}
                    opportunity={opportunity}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="xl:col-span-6">
          <StockAlertCard
            alerts={activeAlerts.data}
            isLoading={activeAlerts.isLoading}
            isError={activeAlerts.isError}
            onRetry={() => activeAlerts.refetch()}
          />
        </div>
        <div className="xl:col-span-6">
          <div className="glass-panel p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-foreground">
                Inventory snapshot
              </h3>
              <Button variant="outline" size="xs" asChild>
                <Link to="/app/products">View products</Link>
              </Button>
            </div>
            <div className="mt-4 space-y-2 text-xs text-muted-foreground">
              <div className="flex items-center justify-between">
                <span>Total products</span>
                <span className="font-semibold text-foreground">
                  {formatNumber(products.length)}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span>Low stock items</span>
                <span
                  className={cn(
                    "font-semibold",
                    lowStockCount > 0 ? "text-rose-300" : "text-emerald-300"
                  )}
                >
                  {formatNumber(lowStockCount)}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span>Average margin</span>
                <span className="font-semibold text-foreground">
                  {formatPercent(averageMargin)}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="xl:col-span-12">
          <CompetitorTable
            competitors={competitors.data}
            isLoading={competitors.isLoading}
            isError={competitors.isError}
            onRetry={() => competitors.refetch()}
          />
        </div>
      </div>
    </div>
  )
}
