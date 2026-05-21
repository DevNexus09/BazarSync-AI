import * as React from "react"
import { Link, useParams } from "react-router-dom"

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
  const { data, isLoading, isError, error, refetch } = useProduct(productId)
  const { mutateAsync: updateProduct, isPending } = useUpdateProduct()
  const [successMessage, setSuccessMessage] = React.useState<string | null>(null)
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null)

  const handleSubmit = async (input: ProductInput) => {
    if (!productId) {
      return
    }
    setSuccessMessage(null)
    setErrorMessage(null)

    try {
      await updateProduct({ productId, input })
      setSuccessMessage("Product updated successfully.")
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
      <PageHeader
        title="Edit product"
        description="Update product details, pricing, and specs for competitor monitoring."
        action={
          <Button variant="outline" size="sm" asChild>
            <Link to="/app/products">Back to products</Link>
          </Button>
        }
      />

      <ProductForm
        key={data.id}
        onSubmit={handleSubmit}
        initialValues={data}
        isSubmitting={isPending}
        successMessage={successMessage}
        errorMessage={errorMessage}
        submitLabel="Save changes"
      />
    </div>
  )
}
