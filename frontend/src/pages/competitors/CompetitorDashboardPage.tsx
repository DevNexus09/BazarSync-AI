import axios from "axios"
import { useEffect, useMemo, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { InlineAlert } from "@/components/common/inline-alert"
import { PageHeader } from "@/components/common/page-header"
import { Phase5Dashboard } from "@/components/dashboard/phase5-dashboard"
import { Input } from "@/components/ui/input"
import { useProducts } from "@/hooks/use-products"
import { formatCurrency, formatNumber, formatPercent } from "@/utils/formatters"
import { getErrorMessage } from "@/utils/errors"
import { cn } from "@/lib/utils"

import { CompetitorTable } from "./components/CompetitorTable"
import { EmptyState } from "./components/EmptyState"
import { ErrorState } from "./components/ErrorState"
import { LoadingState } from "./components/LoadingState"
import { RunScraperButton } from "./components/RunScraperButton"
import { competitorsQueryKey, useCompetitors } from "./hooks/useCompetitors"
import { useRunScraper } from "./hooks/useRunScraper"
import { useScrapeRunStatus } from "./hooks/useScrapeRunStatus"

const getAuthAwareMessage = (error: unknown, fallback: string) => {
  if (axios.isAxiosError(error) && error.response?.status === 401) {
    return "Your session has expired. Please sign in again."
  }
  return getErrorMessage(error, fallback)
}

const isInStock = (status: string) => {
  const normalized = status.toLowerCase()
  return !normalized.includes("out") && !normalized.includes("unavailable")
}

const normalizeStatus = (status?: string | null) => status?.toLowerCase()

export default function CompetitorDashboardPage() {
  const [selectedProductId, setSelectedProductId] = useState("")
  const [activeScrapeRunId, setActiveScrapeRunId] = useState<string | null>(null)
  const [scrapeStarted, setScrapeStarted] = useState(false)
  const [showScrapeSuccess, setShowScrapeSuccess] = useState(false)
  const queryClient = useQueryClient()

  const {
    data: products,
    isLoading: isProductsLoading,
    isError: isProductsError,
    error: productsError,
  } = useProducts()

  const activeProductId = useMemo(() => {
    if (!products || products.length === 0) {
      return ""
    }

    if (selectedProductId) {
      return products.some((product) => product.id === selectedProductId)
        ? selectedProductId
        : ""
    }

    return products.length === 1 ? products[0].id : ""
  }, [products, selectedProductId])
  const selectedProduct = products?.find(
    (product) => product.id === activeProductId
  )

  const {
    data: competitors,
    isLoading: isCompetitorsLoading,
    isError: isCompetitorsError,
    error: competitorsError,
    refetch: refetchCompetitors,
  } = useCompetitors(activeProductId || null)

  const runScraper = useRunScraper(activeProductId || null)
  const scrapeRunStatus = useScrapeRunStatus(
    activeProductId ? activeScrapeRunId : null
  )

  useEffect(() => {
    if (!activeProductId) {
      return
    }

    if (normalizeStatus(scrapeRunStatus.data?.status) === "completed") {
      queryClient.invalidateQueries({
        queryKey: competitorsQueryKey(activeProductId),
      })
      const showTimeout = window.setTimeout(() => {
        setShowScrapeSuccess(true)
      }, 0)
      const resetTimeout = window.setTimeout(() => {
        setShowScrapeSuccess(false)
        setScrapeStarted(false)
        setActiveScrapeRunId(null)
      }, 2500)
      return () => {
        window.clearTimeout(showTimeout)
        window.clearTimeout(resetTimeout)
      }
    }
  }, [activeProductId, queryClient, scrapeRunStatus.data?.status])

  const scraperRunFailure =
    normalizeStatus(scrapeRunStatus.data?.status) === "failed"
      ? scrapeRunStatus.data?.error_message || "Scraper failed. Please try again."
      : null

  useEffect(() => {
    if (scraperRunFailure) {
      const timeout = window.setTimeout(() => {
        setScrapeStarted(false)
      }, 0)
      return () => window.clearTimeout(timeout)
    }
  }, [scraperRunFailure])

  const scraperError = runScraper.isError
    ? getAuthAwareMessage(
        runScraper.error,
        "Scraper failed to start. Please try again."
      )
    : scraperRunFailure

  const scrapeStatus = normalizeStatus(scrapeRunStatus.data?.status)

  const competitorSummary = useMemo(() => {
    if (!competitors || competitors.length === 0) {
      return {
        total: 0,
        averagePrice: null,
        inStock: 0,
        averageSimilarity: null,
      }
    }

    const validPrices = competitors
      .map((competitor) => competitor.price)
      .filter((price): price is number => price !== null)
    const averagePrice =
      validPrices.length > 0
        ? validPrices.reduce((sum, price) => sum + price, 0) / validPrices.length
        : null

    const validSimilarity = competitors
      .map((competitor) => competitor.matchConfidence ?? competitor.similarityScore)
      .filter((score): score is number => score !== null)
    const averageSimilarity =
      validSimilarity.length > 0
        ? validSimilarity.reduce((sum, score) => sum + score, 0) /
          validSimilarity.length
        : null

    const inStock = competitors.filter((competitor) =>
      isInStock(competitor.stockStatus)
    ).length

    return {
      total: competitors.length,
      averagePrice,
      inStock,
      averageSimilarity,
    }
  }, [competitors])

  const productErrorMessage = isProductsError
    ? getAuthAwareMessage(
        productsError,
        "We couldn't load your products. You can still enter a product id."
      )
    : null

  const competitorsErrorMessage = isCompetitorsError
    ? getAuthAwareMessage(
        competitorsError,
        "We couldn't fetch competitor intelligence."
      )
    : null

  const hasProducts = (products?.length ?? 0) > 0
  const hasCompetitors = (competitors?.length ?? 0) > 0
  const canRunScraper = Boolean(activeProductId)
  const isScraperBusy =
    runScraper.isPending ||
    scrapeStarted ||
    scrapeStatus === "pending" ||
    scrapeStatus === "running"

  return (
    <div className="space-y-6">
      <PageHeader
        title="Competitor monitoring"
        description="Track Daraz rivals, benchmark pricing, and trigger fresh scrapes when the market moves."
      />

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <div className="rounded-xl border bg-background p-4 shadow-sm">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3 className="text-sm font-semibold text-foreground">
                Product focus
              </h3>
              <p className="text-sm text-muted-foreground">
                Choose the SKU you want to benchmark against Daraz competitors.
              </p>
            </div>
            <RunScraperButton
              onRun={() => {
                runScraper.reset()
                setScrapeStarted(true)
                setShowScrapeSuccess(false)
                runScraper.mutate(undefined, {
                  onSuccess: (data) => {
                    setActiveScrapeRunId(data.scrape_run_id)
                  },
                  onError: () => {
                    setScrapeStarted(false)
                  },
                })
              }}
              isRunning={isScraperBusy}
              isSuccess={showScrapeSuccess}
              disabled={!canRunScraper}
              errorMessage={scraperError}
            />
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-[2fr_1fr]">
            <div className="space-y-2">
              <label
                className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                htmlFor="competitor-product"
              >
                Product
              </label>
              {hasProducts ? (
                <select
                  id="competitor-product"
                  value={activeProductId}
                  onChange={(event) => {
                    setSelectedProductId(event.target.value)
                    setActiveScrapeRunId(null)
                    setScrapeStarted(false)
                    setShowScrapeSuccess(false)
                    runScraper.reset()
                  }}
                  className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  disabled={isProductsLoading}
                >
                  {products && products.length > 1 ? (
                    <option value="" disabled>
                      Select a product
                    </option>
                  ) : null}
                  {products?.map((product) => (
                    <option key={product.id} value={product.id}>
                      {product.title}
                    </option>
                  ))}
                </select>
              ) : (
                <Input
                  id="competitor-product"
                  value={selectedProductId}
                  onChange={(event) => {
                    setSelectedProductId(event.target.value)
                    setActiveScrapeRunId(null)
                    setScrapeStarted(false)
                    setShowScrapeSuccess(false)
                    runScraper.reset()
                  }}
                  placeholder="Enter product id"
                  disabled={isProductsLoading}
                />
              )}
              {productErrorMessage ? (
                <InlineAlert
                  variant="error"
                  message={productErrorMessage}
                />
              ) : null}
            </div>
            <div className="rounded-lg border bg-muted/30 p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Selected product
              </p>
              <p className="mt-2 text-sm font-medium text-foreground">
                {selectedProduct?.title ?? "No product selected"}
              </p>
              <p className="text-xs text-muted-foreground">
                {activeProductId
                  ? `ID: ${activeProductId}`
                  : "Add a product to start competitor tracking."}
              </p>
            </div>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
          {[
            {
              label: "Competitors tracked",
              value: hasCompetitors
                ? formatNumber(competitorSummary.total)
                : "—",
            },
            {
              label: "Avg. competitor price",
              value:
                competitorSummary.averagePrice === null
                  ? "—"
                  : formatCurrency(competitorSummary.averagePrice),
            },
            {
              label: "In-stock coverage",
              value: hasCompetitors
                ? `${competitorSummary.inStock}/${competitorSummary.total}`
                : "—",
            },
            {
              label: "Avg. similarity score",
              value:
                competitorSummary.averageSimilarity === null
                  ? "—"
                  : formatPercent(competitorSummary.averageSimilarity * 100),
            },
          ].map((metric) => (
            <div
              key={metric.label}
              className={cn(
                "rounded-xl border bg-background p-4 shadow-sm",
                !hasCompetitors && "opacity-70"
              )}
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {metric.label}
              </p>
              <p className="mt-2 text-2xl font-semibold text-foreground">
                {metric.value}
              </p>
            </div>
          ))}
        </div>
      </div>

      <Phase5Dashboard />

      {!activeProductId ? (
        <EmptyState
          title="Select a product to begin"
          message="Pick a product to unlock competitor intelligence, pricing benchmarks, and stock signals."
        />
      ) : isCompetitorsLoading ? (
        <LoadingState />
      ) : isCompetitorsError || !competitors ? (
        <ErrorState
          message={competitorsErrorMessage ?? undefined}
          onRetry={() => refetchCompetitors()}
        />
      ) : competitors.length > 0 ? (
        <CompetitorTable competitors={competitors} />
      ) : null}
    </div>
  )
}
