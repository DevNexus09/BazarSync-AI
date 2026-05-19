import { Link } from "react-router-dom"

import { ProductList } from "@/components/products/product-list"
import { ErrorState } from "@/components/common/error-state"
import { LoadingState } from "@/components/common/loading-state"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { useProducts } from "@/hooks/use-products"
import { getErrorMessage } from "@/utils/errors"

export default function ProductListPage() {
  const { data, isLoading, isError, error, refetch } = useProducts()

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

  return (
    <div className="space-y-6">
      <PageHeader
        title="Products"
        description="Track the products powering competitor scraping, pricing analytics, and alerts."
        action={
          <Button size="sm" asChild>
            <Link to="/app/products/new">Add product</Link>
          </Button>
        }
      />

      {data.length === 0 ? (
        <div className="rounded-xl border bg-background p-6 text-center shadow-sm">
          <h3 className="text-lg font-semibold text-foreground">
            No products yet
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Add your first product to start competitor scraping and pricing
            alerts.
          </p>
          <Button className="mt-4" asChild>
            <Link to="/app/products/new">Add your first product</Link>
          </Button>
        </div>
      ) : (
        <ProductList products={data} />
      )}
    </div>
  )
}
