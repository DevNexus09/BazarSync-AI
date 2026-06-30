import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import {
  ActivityFeed,
  LatestPriceChanges,
  MarketPosition,
  OpportunityFeed,
  SummaryMetrics,
} from "@/components/dashboard/phase5-dashboard"
import type {
  CompetitorActivity,
  LatestPriceChange,
  MarketPositionCard,
  OpportunityFeedItem,
  PageResponse,
  Phase5Summary,
} from "@/types/phase5-dashboard"

const mocks = vi.hoisted(() => ({
  apiPost: vi.fn(),
}))

vi.mock("@/api/client", () => ({
  default: {
    post: mocks.apiPost,
  },
}))

function renderWithQuery(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  )
}

const page = <T,>(items: T[]): PageResponse<T> => ({
  items,
  total: items.length,
  limit: 5,
  offset: 0,
})

describe("Phase 5 dashboard widgets", () => {
  it("renders summary metrics with the recent event window", () => {
    const summary: Phase5Summary = {
      competitorCount: 7,
      priceDropCount: 3,
      stockoutCount: 2,
      openOpportunityCount: 1,
      lastUpdatedAt: "2026-06-29T12:00:00Z",
      windowHours: 24,
      windowStart: "2026-06-28T12:00:00Z",
      windowEnd: "2026-06-29T12:00:00Z",
      competitorCountScope: "latest_completed_scrape_run",
      eventCountScope: "recent_window",
      opportunityCountScope: "currently_open",
    }

    render(
      <SummaryMetrics
        summary={summary}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
      />
    )

    expect(screen.getByText("7")).toBeInTheDocument()
    expect(screen.getByText("3")).toBeInTheDocument()
    expect(screen.getByText("2")).toBeInTheDocument()
    expect(screen.getByText("1")).toBeInTheDocument()
    expect(screen.getByText("Window: 24 hours")).toBeInTheDocument()
  })

  it("formats latest price changes with BDT values and price badges", () => {
    const item: LatestPriceChange = {
      id: "price-1",
      competitorId: "competitor-1",
      competitor: "Shop A",
      productId: "product-1",
      product: "Dove Lotion",
      oldPrice: 320,
      newPrice: 290,
      changeAmount: 30,
      changePercentage: 9.375,
      eventType: "PRICE_DROP",
      eventTime: "2026-06-29T12:00:00Z",
      severity: "HIGH",
    }

    render(
      <LatestPriceChanges
        data={page([item])}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        offset={0}
        setOffset={vi.fn()}
      />
    )

    expect(screen.getByText("Shop A")).toBeInTheDocument()
    expect(screen.getByText("Price drop")).toBeInTheDocument()
    expect(screen.getByText(/BDT\s*320/)).toBeInTheDocument()
    expect(screen.getByText(/BDT\s*290/)).toBeInTheDocument()
    expect(screen.getByText("9.4%")).toBeInTheDocument()
  })

  it("renders all supported activity event types", () => {
    const events: CompetitorActivity[] = [
      "PRICE_DROP",
      "PRICE_RISE",
      "OUT_OF_STOCK",
      "BACK_IN_STOCK",
      "NEW_COMPETITOR",
      "COMPETITOR_REMOVED",
    ].map((eventType, index) => ({
      id: `activity-${index}`,
      eventType: eventType as CompetitorActivity["eventType"],
      competitorId: `competitor-${index}`,
      competitor: `Competitor ${index}`,
      productId: "product-1",
      product: "Dove Lotion",
      description: "A competitor event occurred.",
      severity: "MEDIUM",
      eventTime: "2026-06-29T12:00:00Z",
      supportingValues: null,
    }))

    render(
      <ActivityFeed
        data={page(events)}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        offset={0}
        setOffset={vi.fn()}
      />
    )

    expect(screen.getByText("Price drop")).toBeInTheDocument()
    expect(screen.getByText("Price rise")).toBeInTheDocument()
    expect(screen.getByText("Out of stock")).toBeInTheDocument()
    expect(screen.getByText("Back in stock")).toBeInTheDocument()
    expect(screen.getByText("New competitor")).toBeInTheDocument()
    expect(screen.getByText("Competitor removed")).toBeInTheDocument()
  })

  it("shows missing revenue as insufficient sales history", () => {
    renderWithQuery(
      <OpportunityFeed
        data={page([
          opportunity({
            estimatedRevenue: null,
            estimatedRevenueState: "insufficient_data",
          }),
        ])}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        offset={0}
        setOffset={vi.fn()}
      />
    )

    expect(screen.getByText("Insufficient sales history")).toBeInTheDocument()
    expect(screen.queryByText(/BDT\s*0/)).not.toBeInTheDocument()
  })

  it("runs opportunity acknowledge and dismiss actions", async () => {
    mocks.apiPost.mockResolvedValue({ data: {} })
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const user = userEvent.setup()

    renderWithQuery(
      <OpportunityFeed
        data={page([opportunity({ id: "opportunity-1" })])}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        offset={0}
        setOffset={vi.fn()}
      />
    )

    await user.click(screen.getByRole("button", { name: /acknowledge/i }))
    await user.click(screen.getByRole("button", { name: /dismiss/i }))

    expect(mocks.apiPost).toHaveBeenCalledWith(
      "/market-opportunities/opportunity-1/acknowledge"
    )
    expect(mocks.apiPost).toHaveBeenCalledWith(
      "/market-opportunities/opportunity-1/dismiss"
    )
  })

  it("renders loading, empty, and error states", () => {
    const { rerender } = render(
      <LatestPriceChanges
        isLoading
        isError={false}
        onRetry={vi.fn()}
        offset={0}
        setOffset={vi.fn()}
      />
    )
    expect(screen.getByText("Loading Phase 5 dashboard data")).toBeInTheDocument()

    rerender(
      <LatestPriceChanges
        data={page([])}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        offset={0}
        setOffset={vi.fn()}
      />
    )
    expect(
      screen.getByText("No price drops or rises in this window.")
    ).toBeInTheDocument()

    rerender(
      <LatestPriceChanges
        isLoading={false}
        isError
        onRetry={vi.fn()}
        offset={0}
        setOffset={vi.fn()}
      />
    )
    expect(screen.getByText("Price changes unavailable")).toBeInTheDocument()
  })

  it("renders market position without seller rank when rank is missing", () => {
    const data: MarketPositionCard = {
      sellerProductPrice: 350,
      lowestCompetitorPrice: 290,
      medianCompetitorPrice: 320,
      highestCompetitorPrice: 500,
      strongestCompetitorId: "competitor-1",
      sellerPriceDifferenceFromMarketMedian: 30,
      totalActiveCompetitors: 7,
      totalInStockCompetitors: 5,
      rankingLastUpdatedAt: "2026-06-29T12:00:00Z",
      sellerPriceRank: null,
    }

    render(
      <MarketPosition
        product={product()}
        data={data}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
      />
    )

    expect(screen.getByText("Market median")).toBeInTheDocument()
    expect(screen.queryByText(/Seller price rank/i)).not.toBeInTheDocument()
  })
})

function opportunity(
  overrides: Partial<OpportunityFeedItem> = {}
): OpportunityFeedItem {
  return {
    id: "opportunity-1",
    opportunityLevel: "HIGH",
    opportunityScore: 82,
    estimatedRevenue: 12500,
    estimatedRevenueState: "estimated",
    recommendedAction: "RAISE_PRICE",
    confidenceScore: 88,
    explanation: "Strong competitor went out of stock.",
    evidenceSummary: "trigger: stockout",
    status: "OPEN",
    detectedAt: "2026-06-29T12:00:00Z",
    ...overrides,
  }
}

function product() {
  return {
    id: "product-1",
    title: "Dove Lotion",
    description: "",
    category: "Beauty",
    specifications: {},
    costPrice: 200,
    sellingPrice: 350,
    stockQuantity: 12,
    supplierLeadTime: 3,
    minimumMargin: 20,
  }
}
