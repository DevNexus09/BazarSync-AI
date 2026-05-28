import * as React from "react"
import { Link } from "react-router-dom"

import { ProductForm } from "@/components/products/product-form"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { useCreateProduct } from "@/hooks/use-products"
import type { ProductInput } from "@/types/product"
import { getErrorMessage } from "@/utils/errors"

export default function ProductFormPage() {
  const { mutateAsync, isPending } = useCreateProduct()
  const [successMessage, setSuccessMessage] = React.useState<string | null>(null)
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null)
  const [resetKey, setResetKey] = React.useState(0)

  const handleSubmit = async (input: ProductInput) => {
    setSuccessMessage(null)
    setErrorMessage(null)

    try {
      await mutateAsync(input)
      setSuccessMessage("Product saved. It will now feed pricing and alert engines.")
      setResetKey((prev) => prev + 1)
    } catch (error) {
      setErrorMessage(getErrorMessage(error, "Unable to save this product."))
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Add a product"
        description="Add SKUs to power competitor scraping, AI pricing, and Telegram alerts."
        action={
          <Button variant="outline" size="sm" asChild>
            <Link to="/app/products">View products</Link>
          </Button>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-xl border bg-background p-6 shadow-sm">
          <ProductForm
            key={resetKey}
            onSubmit={handleSubmit}
            isSubmitting={isPending}
            successMessage={successMessage}
            errorMessage={errorMessage}
            submitLabel="Save product"
          />
        </div>
        <div className="space-y-4">
          <div className="rounded-xl border bg-background p-5 shadow-sm">
            <h3 className="text-lg font-semibold text-foreground">
              Why we collect these fields
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              BazarSync AI combines pricing, descriptions, and specifications to
              improve competitor matching and alert quality.
            </p>
            <ul className="mt-4 space-y-3 text-sm text-muted-foreground">
              <li>Cost + selling price power AI pricing recommendations.</li>
              <li>Stock + lead time help forecast restock risk.</li>
              <li>Descriptions + specs reduce false competitor matches.</li>
              <li>Minimum margin protects profitability during discounts.</li>
            </ul>
          </div>
          <div className="rounded-xl border bg-muted/40 p-5 text-sm text-muted-foreground">
            Tip: Add clear specs like storage, color, or size to improve matching.
          </div>
        </div>
      </div>
    </div>
  )
}
