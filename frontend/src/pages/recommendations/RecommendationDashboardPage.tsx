import { useMemo, useState } from "react"

import { InlineAlert } from "@/components/common/inline-alert"
import { PageHeader } from "@/components/common/page-header"
import { Input } from "@/components/ui/input"
import { useProducts } from "@/hooks/use-products"
import { getErrorMessage } from "@/utils/errors"

import { AnalyticsStats } from "./components/AnalyticsStats"
import { EmptyRecommendationState } from "./components/EmptyRecommendationState"
import { GenerateRecommendationButton } from "./components/GenerateRecommendationButton"
import { RecommendationCard } from "./components/RecommendationCard"
import { RecommendationSkeleton } from "./components/RecommendationSkeleton"
import { RevenueOpportunityCard } from "./components/RevenueOpportunityCard"
import { useRecommendation } from "./hooks/useRecommendation"

export default function RecommendationDashboardPage() {
  const [selectedProductId, setSelectedProductId] = useState("")

  const {
    data: products,
    isLoading: isProductsLoading,
    isError: isProductsError,
    error: productsError,
  } = useProducts()

  const activeProductId = selectedProductId || products?.[0]?.id || ""
  const selectedProduct = products?.find(
    (product) => product.id === activeProductId
  )

  const {
    data,
    isLoading,
    isGenerating,
    isFetching,
    isQueued,
    errorMessage,
    generateRecommendation,
  } = useRecommendation(activeProductId || null)

  const productErrorMessage = useMemo(() => {
    if (!isProductsError) {
      return null
    }
    return getErrorMessage(
      productsError,
      "We couldn't load your products. You can still enter a product id."
    )
  }, [isProductsError, productsError])

  const canGenerate = Boolean(activeProductId) && !isProductsLoading
  const showSkeleton = isLoading && !data

  return (
    <div className="space-y-6">
      <PageHeader
        title="AI recommendations"
        description="Bangla insights backed by deterministic analytics."
        action={
          <GenerateRecommendationButton
            onGenerate={() => generateRecommendation()}
            isLoading={isGenerating}
            disabled={!canGenerate}
          />
        }
      />

      <div className="rounded-xl border bg-background p-4 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h3 className="text-sm font-semibold text-foreground">
              Recommendation scope
            </h3>
            <p className="text-sm text-muted-foreground">
              Select a product to generate an AI pricing recommendation.
            </p>
          </div>
          {data?.createdAt ? (
            <span className="text-xs text-muted-foreground">
              Last generated: {new Date(data.createdAt).toLocaleString()}
              {isFetching ? " · Updating..." : ""}
            </span>
          ) : null}
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-[2fr_1fr]">
          <div className="space-y-2">
            <label
              className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
              htmlFor="recommendation-product"
            >
              Product
            </label>
            {products && products.length > 0 ? (
              <select
                id="recommendation-product"
                value={activeProductId}
                onChange={(event) => setSelectedProductId(event.target.value)}
                className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                disabled={isProductsLoading}
              >
                {products.map((product) => (
                  <option key={product.id} value={product.id}>
                    {product.title}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                id="recommendation-product"
                value={selectedProductId}
                onChange={(event) => setSelectedProductId(event.target.value)}
                placeholder="Enter product id"
                disabled={isProductsLoading}
              />
            )}
            {productErrorMessage ? (
              <InlineAlert variant="error" message={productErrorMessage} />
            ) : null}
          </div>

          <div className="rounded-lg border bg-muted/30 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Selected product
            </p>
            <p className="mt-2 text-sm font-medium text-foreground">
              {selectedProduct?.title ?? "No product selected"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {selectedProduct?.category ?? "Category not set"}
            </p>
          </div>
        </div>
      </div>

      {errorMessage ? (
        <InlineAlert
          variant="error"
          message={errorMessage}
        />
      ) : null}
      {isQueued ? (
        <InlineAlert
          variant="info"
          message="Recommendation generation queued. We'll update this view once it's ready."
        />
      ) : null}

      {showSkeleton ? (
        <RecommendationSkeleton />
      ) : data ? (
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
          <RecommendationCard
            recommendation={data.recommendation}
            productTitle={selectedProduct?.title ?? "Selected product"}
            createdAt={data.createdAt}
          />
          <div className="space-y-4">
            <AnalyticsStats analytics={data.analytics} />
            <RevenueOpportunityCard
              value={data.recommendation.revenueOpportunity}
            />
          </div>
        </div>
      ) : (
        <EmptyRecommendationState
          onGenerate={() => generateRecommendation()}
          isGenerating={isGenerating}
        />
      )}
    </div>
  )
}
