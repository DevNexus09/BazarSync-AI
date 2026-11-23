import * as React from "react"
import { Link, useNavigate } from "react-router-dom"
import { ChevronLeft } from "lucide-react"

import { ProductForm } from "@/components/products/product-form"
import { PageHeader } from "@/components/common/page-header"
import { useCreateProduct } from "@/hooks/use-products"
import type { ProductInput } from "@/types/product"
import { getErrorMessage } from "@/utils/errors"

export default function ProductFormPage() {
  const navigate = useNavigate()
  const { mutateAsync, isPending } = useCreateProduct()
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null)

  const handleSubmit = async (input: ProductInput) => {
    setErrorMessage(null)

    try {
      const created = await mutateAsync(input)
      navigate(created?.id ? `/app/products/${created.id}` : "/app/products")
    } catch (error) {
      setErrorMessage(getErrorMessage(error, "Unable to save this product."))
    }
  }

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
        <PageHeader
          title="Add a product"
          description="Cost, price and specs power competitor matching, AI pricing and alerts."
        />
      </div>

      <ProductForm
        onSubmit={handleSubmit}
        isSubmitting={isPending}
        errorMessage={errorMessage}
        submitLabel="Save product"
        cancelHref="/app/products"
      />
    </div>
  )
}
