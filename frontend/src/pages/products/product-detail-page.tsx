import * as React from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  CalendarPlus,
  CheckCircle2,
  ChevronLeft,
  Circle,
  Eye,
  Pencil,
  ReceiptText,
  ShieldCheck,
  Trash2,
} from "lucide-react"

import { ErrorState } from "@/components/common/error-state"
import { InlineAlert } from "@/components/common/inline-alert"
import { LoadingState } from "@/components/common/loading-state"
import { DeadStockReadinessPanel } from "@/components/dead-stock/DeadStockReadinessPanel"
import { ProductAvatar, ProductStatusBadge } from "@/components/products/product-list"
import { Button } from "@/components/ui/button"
import { KpiTile } from "@/components/ui/kpi-tile"
import { useDeadStockReadiness, useDeadStockRecalculation } from "@/hooks/useDeadStock"
import { useDeleteProduct, useProduct } from "@/hooks/use-products"
import { formatCurrency, formatDateTime, formatNumber, formatPercent } from "@/utils/formatters"
import { getErrorMessage } from "@/utils/errors"
import { getActualMargin } from "@/utils/product"
import { cn } from "@/lib/utils"

const setupCards = [
  {
    key: "receipt",
    title: "Inventory receipt",
    description: "Stock-in date and quantity, so inventory age can be calculated.",
    label: "Add receipt",
    href: (id: string) => `/app/inventory/receipts/new?productId=${id}`,
    icon: CalendarPlus,
  },
  {
    key: "sales",
    title: "Sales records",
    description: "Completed sales, so last sale and velocity are known.",
    label: "Import sales",
    href: (id: string) => `/app/sales/import?productId=${id}`,
    icon: ReceiptText,
  },
  {
    key: "pricing",
    title: "Pricing policy",
    description: "Margin, discount limits and price increment for MarginGuard.",
    label: "Set policy",
    href: (id: string) => `/app/pricing/policy-setup?productId=${id}`,
    icon: ShieldCheck,
  },
  {
    key: "visibility",
    title: "Visibility metrics",
    description: "Impressions, clicks, rank or listing quality for SEO recovery.",
    label: "Add metrics",
    href: (id: string) => `/app/products/${id}/visibility`,
    icon: Eye,
  },
]

export default function ProductDetailPage() {
  const { productId } = useParams<{ productId: string }>()
  const navigate = useNavigate()
  const product = useProduct(productId)
  const readiness = useDeadStockReadiness(productId)
  const recalculation = useDeadStockRecalculation(productId)
  const deletion = useDeleteProduct()
  const [deleteError, setDeleteError] = React.useState<string | null>(null)

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

  const p = product.data
  const margin = getActualMargin(p)
  const meetsMargin = margin >= p.minimumMargin
  const specs = Object.entries(p.specifications ?? {}).filter(([, value]) => value)

  const handleDelete = async () => {
    if (!window.confirm("Delete this product permanently? This cannot be undone.")) return
    setDeleteError(null)
    try {
      await deletion.mutateAsync(productId)
      navigate("/app/products")
    } catch (err) {
      setDeleteError(getErrorMessage(err, "We couldn't delete the product. Please try again."))
    }
  }

  const readinessChecks = [
    { label: "Ready for analysis", ok: readiness.data?.ready },
    { label: "Can classify dead stock", ok: readiness.data?.canClassifyDeadStock },
    { label: "Can estimate locked capital", ok: readiness.data?.canEstimateLockedCapital },
    { label: "Can recommend recovery", ok: readiness.data?.canGenerateRecoveryRecommendation },
  ]

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <Link
          to="/app/products"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft aria-hidden className="size-4" />
          Products
        </Link>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-4">
            <ProductAvatar title={p.title} className="size-14 text-xl" />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="heading-font text-2xl font-semibold text-foreground">{p.title}</h2>
                <ProductStatusBadge status={p.status} />
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {[p.sku && `SKU ${p.sku}`, p.category || "Uncategorized", p.updatedAt && `Updated ${formatDateTime(p.updatedAt)}`]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button
              variant="outline"
              onClick={handleDelete}
              disabled={deletion.isPending}
              className="hover:text-danger"
            >
              <Trash2 /> {deletion.isPending ? "Deleting..." : "Delete"}
            </Button>
            <Button asChild>
              <Link to={`/app/products/${productId}/edit`}>
                <Pencil /> Edit product
              </Link>
            </Button>
          </div>
        </div>
      </div>

      {deleteError ? <InlineAlert variant="error" message={deleteError} /> : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiTile
          label="Selling price"
          value={formatCurrency(p.sellingPrice)}
          delta={`Cost ${formatCurrency(p.costPrice)}`}
        />
        <KpiTile
          label="Margin"
          value={
            <span className={meetsMargin ? "text-success" : "text-danger"}>{formatPercent(margin)}</span>
          }
          delta={`Minimum ${formatPercent(p.minimumMargin)}${meetsMargin ? "" : " · below target"}`}
          hint="(Selling price − cost) ÷ selling price."
        />
        <KpiTile
          label="In stock"
          value={p.stockQuantity > 0 ? formatNumber(p.stockQuantity) : "Out of stock"}
          delta={p.stockQuantity > 0 ? `${formatCurrency(p.costPrice * p.stockQuantity)} at cost` : undefined}
        />
        <KpiTile
          label="Supplier lead time"
          value={`${formatNumber(p.supplierLeadTime)} days`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,360px)]">
        <section className="glass-panel space-y-6 p-5" aria-label="Product overview">
          <div>
            <h3 className="text-sm font-semibold text-foreground">Description</h3>
            <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
              {p.description || "No description yet."}
            </p>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-foreground">Specifications</h3>
            {specs.length ? (
              <dl className="mt-3 grid gap-x-6 gap-y-3 sm:grid-cols-2">
                {specs.map(([key, value]) => (
                  <div key={key} className="border-b border-border/40 pb-2">
                    <dt className="text-xs capitalize text-muted-foreground">{key.replace(/_/g, " ")}</dt>
                    <dd className="mt-0.5 text-sm font-medium text-foreground">{value}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">
                No specifications.{" "}
                <Link to={`/app/products/${productId}/edit`} className="text-primary hover:underline">
                  Add some
                </Link>{" "}
                to improve competitor matching.
              </p>
            )}
          </div>

          <div>
            <h3 className="text-sm font-semibold text-foreground">Unit economics</h3>
            <dl className="mt-3 grid gap-3 sm:grid-cols-3">
              <Stat label="Profit per unit" value={formatCurrency(p.sellingPrice - p.costPrice)} />
              <Stat label="Stock value at cost" value={formatCurrency(p.costPrice * p.stockQuantity)} />
              <Stat label="Stock value at price" value={formatCurrency(p.sellingPrice * p.stockQuantity)} />
            </dl>
          </div>
        </section>

        <section className="glass-panel flex flex-col p-5" aria-label="Analysis readiness">
          <h3 className="text-sm font-semibold text-foreground">Analysis readiness</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            What dead-stock analysis can do with the data on file.
          </p>
          <ul className="mt-4 space-y-3">
            {readinessChecks.map((check) => {
              const Icon = check.ok ? CheckCircle2 : Circle
              return (
                <li key={check.label} className="flex items-center gap-2 text-sm">
                  <Icon
                    aria-hidden
                    className={cn("size-4", check.ok ? "text-success" : "text-muted-foreground")}
                  />
                  <span className={check.ok ? "text-foreground" : "text-muted-foreground"}>
                    {check.label}
                  </span>
                  <span className="sr-only">{check.ok ? "yes" : "no"}</span>
                </li>
              )
            })}
          </ul>
          <Button
            className="mt-5 w-full"
            variant="outline"
            onClick={() => recalculation.mutate()}
            disabled={recalculation.isPending}
          >
            {recalculation.isPending ? "Queuing analysis..." : "Run dead stock analysis"}
          </Button>
          {recalculation.isSuccess ? (
            <p className="mt-2 text-xs text-muted-foreground">Analysis queued. Results appear shortly.</p>
          ) : null}
          <p className="mt-auto pt-4 text-xs text-muted-foreground">
            Added {formatDateTime(p.createdAt)}
          </p>
        </section>
      </div>

      <section aria-label="Product setup actions" className="space-y-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Complete this product's data</h3>
          <p className="text-sm text-muted-foreground">
            Each source unlocks more accurate pricing, inventory and recovery insights.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {setupCards.map((card) => {
            const Icon = card.icon
            return (
              <Link
                key={card.key}
                to={card.href(productId)}
                className="glass-panel-muted group flex flex-col p-4 transition hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon aria-hidden className="size-4" />
                </span>
                <span className="mt-3 text-sm font-semibold text-foreground">{card.title}</span>
                <span className="mt-1 flex-1 text-xs text-muted-foreground">{card.description}</span>
                <span className="mt-3 text-xs font-medium text-primary group-hover:underline">
                  {card.label} →
                </span>
              </Link>
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

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border/50 bg-muted/20 px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm font-semibold tabular-nums text-foreground">{value}</dd>
    </div>
  )
}
