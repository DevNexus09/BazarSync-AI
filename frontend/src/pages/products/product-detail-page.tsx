import { Link, useParams } from "react-router-dom"
import {
  CalendarPlus,
  Eye,
  FileText,
  Package,
  ReceiptText,
  ShieldCheck,
} from "lucide-react"

import { ErrorState } from "@/components/common/error-state"
import { LoadingState } from "@/components/common/loading-state"
import { PageHeader } from "@/components/common/page-header"
import { DeadStockReadinessPanel } from "@/components/dead-stock/DeadStockReadinessPanel"
import { Button } from "@/components/ui/button"
import { useDeadStockReadiness, useDeadStockRecalculation } from "@/hooks/useDeadStock"
import { useProduct } from "@/hooks/use-products"
import { formatCurrency, formatDateTime, formatNumber, formatPercent } from "@/utils/formatters"
import { getErrorMessage } from "@/utils/errors"

const setupCards = [
  {
    key: "receipt",
    title: "Inventory receipt",
    description: "Add stock-in date and quantity so inventory age can be calculated.",
    label: "Add receipt",
    href: (id: string) => `/app/inventory/receipts/new?productId=${id}`,
    icon: CalendarPlus,
  },
  {
    key: "sales",
    title: "Sales records",
    description: "Import completed or fulfilled sales so last sale and velocity are known.",
    label: "Import sale",
    href: (id: string) => `/app/sales/import?productId=${id}`,
    icon: ReceiptText,
  },
  {
    key: "pricing",
    title: "Pricing policy",
    description: "Set margin, discount limits, and price increment for MarginGuard.",
    label: "Set policy",
    href: (id: string) => `/app/pricing/policy-setup?productId=${id}`,
    icon: ShieldCheck,
  },
  {
    key: "visibility",
    title: "Visibility metrics",
    description: "Add impressions, clicks, rank, or listing quality for SEO recovery evaluation.",
    label: "Add metrics",
    href: (id: string) => `/app/products/${id}/visibility`,
    icon: Eye,
  },
]

export default function ProductDetailPage() {
  const { productId } = useParams<{ productId: string }>()
  const product = useProduct(productId)
  const readiness = useDeadStockReadiness(productId)
  const recalculation = useDeadStockRecalculation(productId)

  if (product.isLoading) return <LoadingState label="Loading product details..." />
  if (product.isError || !product.data || !productId) {
    return (
      <ErrorState
        title="Unable to load product"
        message={getErrorMessage(product.error, "We couldn't fetch this product.")}
        action={<Button variant="outline" onClick={() => product.refetch()}>Retry</Button>}
      />
    )
  }

  const actualMargin =
    product.data.sellingPrice > 0
      ? ((product.data.sellingPrice - product.data.costPrice) / product.data.sellingPrice) * 100
      : 0

  return (
    <div className="space-y-6">
      <PageHeader
        title={product.data.title}
        description="Product details, Phase 9 readiness, and setup actions for dead-stock analysis."
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link to="/app/products">Back to products</Link>
            </Button>
            <Button size="sm" asChild>
              <Link to={`/app/products/${productId}/edit`}>Edit product</Link>
            </Button>
          </div>
        }
      />

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.75fr)]">
        <div className="glass-panel p-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Package className="size-4" />
            Product information
          </h3>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <Detail label="Category" value={product.data.category || "Uncategorized"} />
            <Detail label="Stock" value={`${formatNumber(product.data.stockQuantity)} units`} />
            <Detail label="Cost" value={formatCurrency(product.data.costPrice)} />
            <Detail label="Selling price" value={formatCurrency(product.data.sellingPrice)} />
            <Detail label="Actual margin" value={formatPercent(actualMargin)} />
            <Detail label="Minimum margin" value={formatPercent(product.data.minimumMargin)} />
            <Detail label="Supplier lead time" value={`${formatNumber(product.data.supplierLeadTime)} days`} />
            <Detail label="Created" value={formatDateTime(product.data.createdAt)} />
          </div>
          {product.data.description ? (
            <div className="mt-4 rounded-lg border border-border/70 bg-muted/20 p-3 text-sm text-muted-foreground">
              {product.data.description}
            </div>
          ) : null}
        </div>

        <div className="glass-panel p-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <FileText className="size-4" />
            Product Status
          </h3>
          <div className="mt-4 space-y-3">
            <Detail label="Ready" value={readiness.data?.ready ? "Yes" : "No"} />
            <Detail label="Can classify" value={readiness.data?.canClassifyDeadStock ? "Yes" : "No"} />
            <Detail label="Can estimate capital" value={readiness.data?.canEstimateLockedCapital ? "Yes" : "No"} />
            <Detail label="Can recommend recovery" value={readiness.data?.canGenerateRecoveryRecommendation ? "Yes" : "No"} />
          </div>
          <Button
            className="mt-4"
            size="sm"
            onClick={() => recalculation.mutate()}
            disabled={recalculation.isPending}
          >
            {recalculation.isPending ? "Queuing analysis..." : "Run dead stock analysis"}
          </Button>
        </div>
      </section>

      <section className="glass-panel p-4" aria-label="Product setup actions">
        <h3 className="text-sm font-semibold text-foreground">Setup and data completion</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Add the source data this product needs for inventory age, sales velocity,
          safe pricing, recovery estimates, and SEO evaluation.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {setupCards.map((card) => {
            const Icon = card.icon
            return (
              <div key={card.key} className="rounded-lg border border-border/70 bg-muted/20 p-3">
                <Icon className="size-4 text-primary" />
                <h4 className="mt-3 text-sm font-semibold text-foreground">{card.title}</h4>
                <p className="mt-1 min-h-12 text-xs text-muted-foreground">{card.description}</p>
                <Button className="mt-3" size="sm" variant="outline" asChild>
                  <Link to={card.href(productId)}>{card.label}</Link>
                </Button>
              </div>
            )
          })}
        </div>
      </section>

      <DeadStockReadinessPanel
        readiness={readiness.data}
        isError={readiness.isError}
        onRunAnalysis={() => recalculation.mutate()}
        runAnalysisPending={recalculation.isPending}
      />
    </div>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-right text-sm font-medium text-foreground">{value}</span>
    </div>
  )
}
