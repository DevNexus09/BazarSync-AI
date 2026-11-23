import * as React from "react"
import { Link } from "react-router-dom"
import { PackagePlus, Plus, Search } from "lucide-react"

import { InlineAlert } from "@/components/common/inline-alert"
import { ProductList } from "@/components/products/product-list"
import { getActualMargin } from "@/utils/product"
import { ErrorState } from "@/components/common/error-state"
import { LoadingState } from "@/components/common/loading-state"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { KpiTile } from "@/components/ui/kpi-tile"
import { useDeleteProduct, useProducts } from "@/hooks/use-products"
import { getErrorMessage } from "@/utils/errors"
import { formatCurrency, formatNumber } from "@/utils/formatters"

const STATUS_OPTIONS = ["ACTIVE", "DRAFT", "INACTIVE", "ARCHIVED", "DISCONTINUED"] as const

const selectClass =
  "h-11 rounded-xl border border-border/70 bg-card/70 px-3 text-sm text-foreground outline-none transition focus-visible:border-primary/60 focus-visible:ring-2 focus-visible:ring-primary/30"

export default function ProductListPage() {
  const { data, isLoading, isError, error, refetch } = useProducts()
  const { mutateAsync: deleteProduct, isPending: isDeleting } = useDeleteProduct()
  const [deleteError, setDeleteError] = React.useState<string | null>(null)
  const [deletingId, setDeletingId] = React.useState<string | null>(null)
  const [query, setQuery] = React.useState("")
  const [status, setStatus] = React.useState("")
  const [category, setCategory] = React.useState("")

  const products = React.useMemo(() => data ?? [], [data])
  const categories = React.useMemo(
    () => [...new Set(products.map((p) => p.category).filter(Boolean))].sort(),
    [products]
  )
  const filtered = React.useMemo(() => {
    const needle = query.trim().toLowerCase()
    return products.filter(
      (p) =>
        (!status || (p.status ?? "ACTIVE") === status) &&
        (!category || p.category === category) &&
        (!needle ||
          p.title.toLowerCase().includes(needle) ||
          (p.sku ?? "").toLowerCase().includes(needle))
    )
  }, [products, query, status, category])

  const stats = React.useMemo(
    () => ({
      inventoryValue: products.reduce((sum, p) => sum + p.costPrice * p.stockQuantity, 0),
      belowMargin: products.filter((p) => getActualMargin(p) < p.minimumMargin).length,
      outOfStock: products.filter((p) => p.stockQuantity <= 0).length,
    }),
    [products]
  )

  const handleDelete = async (productId: string) => {
    const confirmed = window.confirm(
      "Delete this product permanently? This cannot be undone."
    )
    if (!confirmed) {
      return
    }

    setDeleteError(null)
    setDeletingId(productId)
    try {
      await deleteProduct(productId)
    } catch (err) {
      setDeleteError(
        getErrorMessage(err, "We couldn't delete the product. Please try again.")
      )
    } finally {
      setDeletingId(null)
    }
  }

  if (isLoading) {
    return <LoadingState label="Loading products..." />
  }

  if (isError || !data) {
    return (
      <ErrorState
        title="Unable to load products"
        message={getErrorMessage(error, "We couldn't fetch your products.")}
        action={
          <Button variant="outline" onClick={() => refetch()}>
            Retry
          </Button>
        }
      />
    )
  }

  const addButton = (
    <Button asChild>
      <Link to="/app/products/new">
        <Plus /> Add product
      </Link>
    </Button>
  )

  if (products.length === 0) {
    return (
      <div className="space-y-6">
        <PageHeader title="Products" />
        <EmptyState
          icon={PackagePlus}
          title="No products yet"
          message="Add your first product to start competitor scraping, pricing analytics and alerts."
          action={addButton}
        />
      </div>
    )
  }

  const hasFilters = Boolean(query || status || category)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Products"
        description="Your catalog powers competitor scraping, pricing analytics and alerts."
        action={addButton}
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile label="Products" value={formatNumber(products.length)} />
        <KpiTile
          label="Inventory value"
          value={formatCurrency(stats.inventoryValue)}
          hint="Cost price × units in stock, across all products."
        />
        <KpiTile
          label="Below minimum margin"
          value={formatNumber(stats.belowMargin)}
          hint="Products whose current selling price earns less than their minimum margin."
        />
        <KpiTile label="Out of stock" value={formatNumber(stats.outOfStock)} />
      </div>

      {deleteError ? <InlineAlert variant="error" message={deleteError} /> : null}

      <section className="glass-panel overflow-hidden" aria-label="Product catalog">
        <div className="flex flex-col gap-3 border-b border-border/60 p-4 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by name or SKU"
              aria-label="Search products"
              className="pl-9"
            />
          </div>
          <div className="grid grid-cols-2 gap-3 sm:flex">
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              aria-label="Filter by status"
              className={selectClass}
            >
              <option value="">All statuses</option>
              {STATUS_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value.charAt(0) + value.slice(1).toLowerCase()}
                </option>
              ))}
            </select>
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              aria-label="Filter by category"
              className={selectClass}
            >
              <option value="">All categories</option>
              {categories.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </div>
        </div>

        {filtered.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={Search}
              title="No products match your filters"
              action={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setQuery("")
                    setStatus("")
                    setCategory("")
                  }}
                >
                  Clear filters
                </Button>
              }
            />
          </div>
        ) : (
          <ProductList
            products={filtered}
            onDelete={handleDelete}
            deletingId={isDeleting ? deletingId : null}
          />
        )}

        <div className="border-t border-border/60 px-4 py-3 text-xs text-muted-foreground">
          {hasFilters
            ? `Showing ${formatNumber(filtered.length)} of ${formatNumber(products.length)} products`
            : `${formatNumber(products.length)} products`}
        </div>
      </section>
    </div>
  )
}
