import axios from "axios"
import { Link, useSearchParams } from "react-router-dom"

import { InlineAlert } from "@/components/common/inline-alert"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useAuth } from "@/hooks/use-auth"
import { useProducts } from "@/hooks/use-products"
import { formatDateTime } from "@/utils/formatters"
import { getErrorMessage } from "@/utils/errors"

import { AnalyticsStats } from "./components/AnalyticsStats"
import { EmptyRecommendationState } from "./components/EmptyRecommendationState"
import { GenerateRecommendationButton } from "./components/GenerateRecommendationButton"
import { RecommendationCard } from "./components/RecommendationCard"
import { RecommendationEvidence } from "./components/RecommendationEvidence"
import { RecommendationSkeleton } from "./components/RecommendationSkeleton"
import { RevenueOpportunityCard } from "./components/RevenueOpportunityCard"
import { useRecommendation } from "./hooks/useRecommendation"

export default function RecommendationDashboardPage() {
  const { logout } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedProductId = searchParams.get("product") ?? ""
  const setSelectedProductId = (productId: string) => {
    const next = new URLSearchParams(searchParams)
    if (productId) next.set("product", productId)
    else next.delete("product")
    setSearchParams(next, { replace: true })
  }

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
    jobStatus,
    generationFailed,
    sessionExpired,
    retryLatest,
    retryStatus,
    errorMessage,
    generateRecommendation,
  } = useRecommendation(activeProductId || null)

  const productError = "We couldn't load your products. You can still enter a product ID."
  const productErrorMessage = isProductsError ? getErrorMessage(productsError, productError) : null
  const canGenerate = Boolean(activeProductId) && !isProductsLoading && !retryStatus
  const showSkeleton = isLoading && !data && !isQueued
  const evidence = import.meta.env.VITE_RECOMMENDATION_DASHBOARD_V2 === "true" ? data?.evidence : undefined
  const generationState = jobStatus === "FAILED" || generationFailed ? "Failed"
    : jobStatus === "RUNNING" ? "Processing"
    : isGenerating ? "Queued"
    : evidence?.insufficient_evidence ? "Insufficient evidence"
    : jobStatus === "COMPLETED" || data ? "Completed"
    : isLoading || errorMessage ? null : "Not generated"

  const productsSessionExpired = axios.isAxiosError(productsError)
    && productsError.response?.status === 401

  if (sessionExpired || productsSessionExpired) {
    return (
      <div className="space-y-4">
        <PageHeader title="AI recommendations" />
        <div role="alert">
          <InlineAlert variant="error" message="Your session has expired. Sign in to see your recommendations." />
        </div>
        <Button asChild><Link to="/login" onClick={logout}>Sign in</Link></Button>
      </div>
    )
  }

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
              Select a product to generate a pricing or inventory recommendation.
            </p>
          </div>
          {data?.createdAt ? (
            <span className="text-xs text-muted-foreground">
              Last generated: {formatDateTime(data.createdAt)}
              {isFetching ? " · Updating..." : ""}
            </span>
          ) : null}
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
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
              <InlineAlert variant="error" message={typeof productErrorMessage === "string" ? productErrorMessage : productError} />
            ) : null}
          </div>

          <div className="rounded-lg border bg-muted/30 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Selected product
            </p>
            <p className="mt-2 break-words text-sm font-medium text-foreground">
              {selectedProduct?.title ?? "No product selected"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {selectedProduct?.category ?? "Category not set"}
            </p>
          </div>
        </div>
      </div>

      <div role="status" aria-live="polite" className="text-sm font-medium">
        {generationState ? `Generation status: ${generationState}` : null}
      </div>
      {errorMessage ? (
        <div role="alert" className="space-y-2">
          <InlineAlert variant="error" message={errorMessage} />
          {retryStatus || retryLatest ? (
            <Button variant="outline" onClick={() => void (retryStatus ?? retryLatest)?.()}>
              {retryStatus ? "Retry job status" : "Retry loading"}
            </Button>
          ) : null}
        </div>
      ) : null}

      {showSkeleton ? (
        <RecommendationSkeleton />
      ) : data ? (
        <>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <RecommendationCard
              recommendation={data.recommendation}
              productTitle={selectedProduct?.title ?? "Selected product"}
              createdAt={data.createdAt}
              evidence={evidence}
            />
            <div className="min-w-0 space-y-4">
              <AnalyticsStats analytics={data.analytics} />
              {evidence ? null : <RevenueOpportunityCard value={data.recommendation.revenueOpportunity || null} />}
            </div>
          </div>
          {evidence ? <RecommendationEvidence evidence={evidence} /> : null}
        </>
      ) : isGenerating || errorMessage ? null : (
        <EmptyRecommendationState onGenerate={canGenerate ? generateRecommendation : undefined} />
      )}
    </div>
  )
}
