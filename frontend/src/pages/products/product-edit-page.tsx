import * as React from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { ChevronLeft } from "lucide-react"

import { ErrorState } from "@/components/common/error-state"
import { LoadingState } from "@/components/common/loading-state"
import { PageHeader } from "@/components/common/page-header"
import { ProductForm } from "@/components/products/product-form"
import { Button } from "@/components/ui/button"
import { useProduct, useUpdateProduct } from "@/hooks/use-products"
import type { ProductInput } from "@/types/product"
import { getErrorMessage } from "@/utils/errors"

export default function ProductEditPage() {
  const { productId } = useParams<{ productId: string }>()
  const navigate = useNavigate()
  const { data, isLoading, isError, error, refetch } = useProduct(productId)
  const { mutateAsync: updateProduct, isPending } = useUpdateProduct()
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null)

  const handleSubmit = async (input: ProductInput) => {
    if (!productId) {
      return
    }
    setErrorMessage(null)

    try {
      await updateProduct({ productId, input })
      navigate(`/app/products/${productId}`)
    } catch (err) {
      setErrorMessage(
        getErrorMessage(err, "We couldn't update the product. Please try again.")
      )
    }
  }

  if (isLoading) {
    return <LoadingState label="Loading product details..." />
  }

  if (isError || !data) {
    return (
      <ErrorState
        title="Unable to load product"
        message={getErrorMessage(error, "We couldn't fetch this product.")}
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
      <div className="space-y-4">
        <Link
          to={`/app/products/${data.id}`}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft aria-hidden className="size-4" />
          {data.title}
        </Link>
        <PageHeader
          title="Edit product"
          description="Update details, specifications, pricing and stock for this product."
        />
      </div>

      <ProductForm
        key={data.id}
        onSubmit={handleSubmit}
        initialValues={data}
        isSubmitting={isPending}
        errorMessage={errorMessage}
        submitLabel="Save changes"
        cancelHref={`/app/products/${data.id}`}
      />
    </div>
  )
}
