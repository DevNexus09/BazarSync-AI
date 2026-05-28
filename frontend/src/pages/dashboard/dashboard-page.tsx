import { Link } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/common/error-state"
import { LoadingState } from "@/components/common/loading-state"
import { PageHeader } from "@/components/common/page-header"
import { useProducts } from "@/hooks/use-products"
import type { Product } from "@/types/product"
import { formatCurrency, formatNumber, formatPercent } from "@/utils/formatters"
import { getErrorMessage } from "@/utils/errors"
import { cn } from "@/lib/utils"

const LOW_STOCK_THRESHOLD = 10

function getActualMargin(product: Product) {
  if (product.sellingPrice <= 0) {
    return 0
  }

  return ((product.sellingPrice - product.costPrice) / product.sellingPrice) * 100
}

function getPotentialProfit(product: Product) {
  return (product.sellingPrice - product.costPrice) * product.stockQuantity
}

export default function DashboardPage() {
  const { data, isLoading, isError, error, refetch, isFetching } = useProducts()

  if (isLoading) {
    return <LoadingState label="Loading dashboard..." />
  }

  if (isError || !data) {
    return (
      <ErrorState
        title="Dashboard unavailable"
        message={getErrorMessage(error, "We couldn't load your products yet.")}
        action={
          <Button variant="outline" onClick={() => refetch()}>
            Retry
          </Button>
        }
      />
    )
  }

  const totalProducts = data.length
  const lowStockCount = data.filter(
    (product) => product.stockQuantity <= LOW_STOCK_THRESHOLD
  ).length
  const averageMargin =
    data.length === 0
      ? 0
      : data.reduce((sum, product) => sum + getActualMargin(product), 0) /
        data.length
  const potentialProfit = data.reduce(
    (sum, product) => sum + getPotentialProfit(product),
    0
  )

  const attentionList = data
    .filter(
      (product) =>
        product.stockQuantity <= LOW_STOCK_THRESHOLD ||
        getActualMargin(product) < product.minimumMargin
    )
    .slice(0, 4)

  const recentProducts = data.slice(0, 5)

  return (
    <div className="space-y-6">
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
            </Button>
          </div>
          <div className="mt-4 space-y-3">
            {recentProducts.length === 0 ? (
              <div className="rounded-lg border border-dashed bg-muted/40 p-4 text-sm text-muted-foreground">
                Add products to start monitoring competitor prices.
              </div>
            ) : (
              recentProducts.map((product) => (
                <div
                  key={product.id}
                  className="rounded-lg border bg-muted/40 p-3"
                >
                  <p className="text-sm font-semibold text-foreground">
                    {product.title}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Selling {formatCurrency(product.sellingPrice)} · Stock{" "}
                    {formatNumber(product.stockQuantity)}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
