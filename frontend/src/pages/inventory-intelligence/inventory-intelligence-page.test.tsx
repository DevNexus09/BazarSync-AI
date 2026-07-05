import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import InventoryIntelligencePage from "@/pages/inventory-intelligence/inventory-intelligence-page"

const mocks = vi.hoisted(() => ({
  useProducts: vi.fn(),
  useInventoryIntelligenceSummary: vi.fn(),
  useInventoryReorderList: vi.fn(),
  useInventoryRisks: vi.fn(),
  useProductInventoryIntelligence: vi.fn(),
  useRunDailyInventoryWorkflow: vi.fn(),
  useRunProductInventoryWorkflow: vi.fn(),
  useDeadStockSummary: vi.fn(),
  useDeadStockProducts: vi.fn(),
  useProductDeadStockIntelligence: vi.fn(),
  useDeadStockReadiness: vi.fn(),
  useDeadStockRecalculation: vi.fn(),
  useRecoverySimulation: vi.fn(),
}))

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  BarChart: ({ children }: { children: React.ReactNode }) => <div aria-label="age chart">{children}</div>,
  CartesianGrid: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Bar: () => null,
}))

vi.mock("@/hooks/use-products", () => ({ useProducts: mocks.useProducts }))
vi.mock("@/hooks/useInventoryIntelligence", () => ({
  useInventoryIntelligenceSummary: mocks.useInventoryIntelligenceSummary,
  useInventoryReorderList: mocks.useInventoryReorderList,
  useInventoryRisks: mocks.useInventoryRisks,
  useProductInventoryIntelligence: mocks.useProductInventoryIntelligence,
  useRunDailyInventoryWorkflow: mocks.useRunDailyInventoryWorkflow,
  useRunProductInventoryWorkflow: mocks.useRunProductInventoryWorkflow,
}))
vi.mock("@/hooks/useDeadStock", () => ({
  useDeadStockSummary: mocks.useDeadStockSummary,
  useDeadStockProducts: mocks.useDeadStockProducts,
  useProductDeadStockIntelligence: mocks.useProductDeadStockIntelligence,
  useDeadStockReadiness: mocks.useDeadStockReadiness,
  useDeadStockRecalculation: mocks.useDeadStockRecalculation,
  useRecoverySimulation: mocks.useRecoverySimulation,
}))

const query = {
  isLoading: false,
  isError: false,
  isFetching: false,
  refetch: vi.fn(),
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <InventoryIntelligencePage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.useProducts.mockReturnValue({
    data: [{ id: "product-1", title: "Dead Lotion <img src=x onerror=alert(1)>", category: "Beauty" }],
  })
  mocks.useInventoryIntelligenceSummary.mockReturnValue({
    ...query,
    data: {
      totalActiveProducts: 2,
      highRiskProducts: 1,
      criticalRiskProducts: 0,
      productsRequiringReorder: 0,
      productsAlreadyOutOfStock: 0,
      insufficientDataProducts: 0,
      dataFreshnessStatus: "FRESH",
      lastCalculationTime: "2026-07-03T10:00:00Z",
    },
  })
  mocks.useInventoryReorderList.mockReturnValue({ ...query, data: { items: [], total: 0 } })
  mocks.useInventoryRisks.mockReturnValue({ ...query, data: { items: [], total: 0 } })
  mocks.useProductInventoryIntelligence.mockReturnValue({ ...query, data: null })
  mocks.useRunDailyInventoryWorkflow.mockReturnValue({ mutate: vi.fn(), isPending: false, isSuccess: false })
  mocks.useRunProductInventoryWorkflow.mockReturnValue({ mutate: vi.fn(), isPending: false, isSuccess: false })
  mocks.useDeadStockSummary.mockReturnValue({
    ...query,
    data: {
      deadStockCount: 3,
      totalEligibleDeadStockUnits: 24,
      atRiskCount: 2,
      slowMovingCount: 1,
      totalLockedCapital: 24000,
      lockedCapitalCurrency: "BDT",
      estimatedRecoverableCash: 17100,
      recoverableCashCurrency: "BDT",
      monetaryTotalsComparable: true,
      forecastHorizonDays: 14,
      productsRequiringManualReview: 1,
      productsWithInsufficientData: 2,
      formulaVersion: "v1",
      ageDistribution: { "0-30": 1, "31-45": 0, "46-60": 1, "61-90": 2, "91-180": 1, "180+": 1 },
    },
  })
  mocks.useDeadStockProducts.mockReturnValue({
    ...query,
    data: {
      total: 20,
      items: [
        {
          productId: "product-1",
          productName: "Dead Lotion <img src=x onerror=alert(1)>",
          category: "Beauty",
          currentStock: 30,
          eligibleUnsoldQuantity: 24,
          inventoryAgeDays: 92,
          inventoryAgeIsEstimated: true,
          ageSource: "FIRST_POSITIVE_SNAPSHOT",
          daysSinceLastSale: 64,
          classification: "DEAD_STOCK",
          riskScore: 88,
          riskLevel: "CRITICAL",
          lockedCapital: 24000,
          lockedCapitalCurrency: "BDT",
          primaryRecommendation: "DISCOUNT",
          recommendationStatus: "OPEN",
          potentialRecovery: 17100,
          potentialRecoveryLow: 13500,
          potentialRecoveryHigh: 19950,
          dataStatus: "LIMITED",
          lastCalculatedAt: "2026-07-03T10:00:00Z",
        },
        {
          productId: "product-2",
          productName: "At Risk Serum",
          category: "Beauty",
          currentStock: 12,
          eligibleUnsoldQuantity: 8,
          inventoryAgeDays: 61,
          inventoryAgeIsEstimated: false,
          ageSource: "INVENTORY_LOT",
          daysSinceLastSale: 32,
          classification: "AT_RISK",
          riskScore: 62,
          riskLevel: "HIGH",
          lockedCapital: null,
          lockedCapitalCurrency: null,
          primaryRecommendation: "MANUAL_REVIEW",
          recommendationStatus: "INSUFFICIENT_DATA",
          potentialRecovery: null,
          potentialRecoveryLow: null,
          potentialRecoveryHigh: null,
          dataStatus: "INSUFFICIENT",
          lastCalculatedAt: "2026-07-03T09:00:00Z",
        },
      ],
    },
  })
  mocks.useProductDeadStockIntelligence.mockReturnValue({
    ...query,
    data: {
      productId: "product-1",
      productName: "Dead Lotion",
      category: "Beauty",
      currentInventory: 30,
      eligibleUnsoldQuantity: 24,
      inventoryAgeDays: 92,
      inventoryAgeIsEstimated: true,
      inventoryAgeState: "AGE_ESTIMATED",
      ageSource: "FIRST_POSITIVE_SNAPSHOT",
      daysSinceLastSale: 64,
      dailySalesRate: 0.1,
      velocityDataStatus: "SUFFICIENT",
      visibilityStatus: "VISIBILITY_DATA_UNAVAILABLE",
      classification: "DEAD_STOCK",
      riskScore: 88,
      riskLevel: "CRITICAL",
      triggeredRules: ["NO_VALID_SALES", "INVENTORY_AGE_ESTIMATED"],
      lockedCapital: null,
      lockedCapitalCurrency: null,
      primaryRecoveryRecommendation: "DISCOUNT",
      recommendedDiscountRate: 0.1,
      recommendedPrice: 285,
      potentialRecoveredCashLow: 13500,
      potentialRecoveredCash: 17100,
      potentialRecoveredCashHigh: 19950,
      confidence: 58,
      dataStatus: "LIMITED",
      lastUpdatedAt: "2026-07-03T10:00:00Z",
      formulaVersion: "v1",
      recoveryRecommendation: {
        explanation: "A bounded discount is recommended.",
        rejected_actions: [{ action: "SEO_FIX", reasons: ["Reliable visibility evidence is unavailable."] }],
      },
      capitalRecovery: { estimate_status: "BLOCKED_BY_MARGIN_POLICY", estimation_method: "CONSERVATIVE_HEURISTIC" },
      evidence: {},
    },
  })
  mocks.useDeadStockReadiness.mockReturnValue({
    ...query,
    data: {
      productId: "product-1",
      productName: "Dead Lotion",
      ready: false,
      canClassifyDeadStock: false,
      canScoreRisk: true,
      canEstimateLockedCapital: false,
      canGenerateRecoveryRecommendation: false,
      canEstimatePotentialRecovery: false,
      blockingReasons: [
        "MISSING_PRODUCT_COST",
        "MISSING_INVENTORY_AGE_SOURCE",
        "MISSING_MARKETPLACE_FEE_POLICY",
        "MISSING_PRICING_POLICY",
      ],
      nonBlockingReasons: [
        "MISSING_SALES_HISTORY",
        "VISIBILITY_DATA_UNAVAILABLE",
        "MISSING_DEAD_STOCK_ASSESSMENT",
      ],
      checks: {
        current_stock: {
          status: "OK",
          reasonCode: null,
          message: "Current stock is available.",
          blocking: false,
          currentValue: 30,
          nextAction: null,
          href: null,
        },
        product_cost: {
          status: "MISSING",
          reasonCode: "MISSING_PRODUCT_COST",
          message: "Product cost is required to calculate locked capital and safe recovery pricing.",
          blocking: true,
          currentValue: null,
          nextAction: "Add product landed cost.",
          href: "/app/products/product-1/edit",
        },
        inventory_age_source: {
          status: "MISSING",
          reasonCode: "MISSING_INVENTORY_AGE_SOURCE",
          message: "Inventory received date or stock-in history is required to calculate inventory age.",
          blocking: true,
          currentValue: null,
          nextAction: "Add purchase receipt, inventory lot, goods-received date, or stock-in transaction.",
          href: null,
        },
        marketplace_fee_policy: {
          status: "MISSING",
          reasonCode: "MISSING_MARKETPLACE_FEE_POLICY",
          message: "Marketplace fee policy is required before discount recovery can be estimated safely.",
          blocking: true,
          currentValue: null,
          nextAction: "Set up marketplace fees.",
          href: "/app/pricing/fee-setup?productId=product-1",
        },
        pricing_policy: {
          status: "MISSING",
          reasonCode: "MISSING_PRICING_POLICY",
          message: "Pricing policy is required to know the minimum margin, discount limit, and price increment.",
          blocking: true,
          currentValue: null,
          nextAction: "Set up pricing policy.",
          href: null,
        },
        sales_history: {
          status: "MISSING",
          reasonCode: "MISSING_SALES_HISTORY",
          message: "Sales history has not been imported or is insufficient.",
          blocking: false,
          currentValue: null,
          nextAction: "Import completed sales records.",
          href: null,
        },
        visibility_data: {
          status: "UNAVAILABLE",
          reasonCode: "VISIBILITY_DATA_UNAVAILABLE",
          message: "Visibility data is unavailable. SEO recovery recommendations cannot be evaluated yet.",
          blocking: false,
          currentValue: null,
          nextAction: "Connect visibility metrics later.",
          href: null,
        },
        dead_stock_assessment: {
          status: "PENDING_CALCULATION",
          reasonCode: "MISSING_DEAD_STOCK_ASSESSMENT",
          message: "Dead stock assessment has not been calculated for the latest available data.",
          blocking: false,
          currentValue: null,
          nextAction: "Run dead stock analysis.",
          href: null,
        },
        phase9_pipeline: {
          status: "PENDING_CALCULATION",
          reasonCode: "PHASE9_RECALCULATION_REQUIRED",
          message: "Run Phase 9 dead stock analysis after source data has been added.",
          blocking: false,
          currentValue: null,
          nextAction: "Run dead stock analysis.",
          href: null,
        },
      },
      nextActions: [
        {
          key: "add_product_cost",
          label: "Add product cost",
          description: "Required to calculate locked capital and safe recovery pricing.",
          href: "/app/products/product-1/edit",
          implemented: true,
          priority: 1,
        },
        {
          key: "add_inventory_receipt",
          label: "Add inventory receipt",
          description: "Required to calculate inventory age.",
          href: "/app/inventory/receipts/new?productId=product-1",
          implemented: true,
          priority: 2,
        },
        {
          key: "set_up_marketplace_fees",
          label: "Set up marketplace fees",
          description: "Required before discount recovery can be estimated safely.",
          href: "/app/pricing/fee-setup?productId=product-1",
          implemented: true,
          priority: 3,
        },
        {
          key: "set_up_pricing_policy",
          label: "Set up pricing policy",
          description: "Required to enforce minimum margin and discount limits.",
          href: "/app/pricing/policy-setup?productId=product-1",
          implemented: true,
          priority: 4,
        },
        {
          key: "run_dead_stock_analysis",
          label: "Run dead stock analysis",
          description: "Run after required source data has been added.",
          href: null,
          implemented: true,
          priority: 6,
        },
        {
          key: "add_visibility_metrics",
          label: "Add visibility metrics",
          description: "Optional. Required only for SEO recovery recommendations.",
          href: "/app/products/product-1/visibility",
          implemented: true,
          priority: 7,
        },
      ],
      recommendedSetupOrder: [],
      lastCheckedAt: "2026-07-03T10:00:00Z",
    },
  })
  mocks.useDeadStockRecalculation.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mocks.useRecoverySimulation.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    data: null,
  })
})

describe("InventoryIntelligencePage dead-stock dashboard", () => {
  it("renders summary cards, dead-stock rows, at-risk rows, estimates, and escaped product names", () => {
    renderPage()

    expect(screen.getByText("Dead stock recovery")).toBeInTheDocument()
    expect(screen.getByText("Dead-stock products")).toBeInTheDocument()
    expect(screen.getAllByText(/BDT\s*24,000/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/BDT\s*17,100/).length).toBeGreaterThan(0)
    expect(screen.getAllByText("Dead Lotion <img src=x onerror=alert(1)>").length).toBeGreaterThan(0)
    expect(screen.queryByRole("img", { hidden: true })).not.toBeInTheDocument()
    expect(screen.getByText("At Risk Serum")).toBeInTheDocument()
    expect(screen.getAllByText("Estimated age").length).toBeGreaterThan(0)
  })

  it("shows readiness guidance, recovery recommendation, and rejected action reasons", async () => {
    const user = userEvent.setup()
    renderPage()
    await user.selectOptions(screen.getByLabelText("Product"), "product-1")

    expect(screen.getByText("Dead stock analysis setup incomplete")).toBeInTheDocument()
    expect(screen.getAllByText(/Product cost is required/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Inventory received date or stock-in history/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Marketplace fee policy is required/).length).toBeGreaterThan(0)
    expect(screen.getByRole("link", { name: "Set up pricing policy" })).toHaveAttribute(
      "href",
      "/app/pricing/policy-setup?productId=product-1"
    )
    expect(screen.getByRole("link", { name: "Add inventory receipt" })).toHaveAttribute(
      "href",
      "/app/inventory/receipts/new?productId=product-1"
    )
    expect(screen.getByRole("link", { name: "Add visibility metrics" })).toHaveAttribute(
      "href",
      "/app/products/product-1/visibility"
    )
    expect(screen.getByRole("link", { name: "Add product cost" })).toHaveAttribute(
      "href",
      "/app/products/product-1/edit"
    )
    expect(screen.getByRole("link", { name: "Set up marketplace fees" })).toHaveAttribute(
      "href",
      "/app/pricing/fee-setup?productId=product-1"
    )
    expect(screen.getAllByText(/Visibility data is unavailable/).length).toBeGreaterThan(0)
    expect(screen.getByText(/A bounded discount is recommended/)).toBeInTheDocument()
    expect(screen.getByText(/Reliable visibility evidence is unavailable/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /estimate recovery/i })).toBeDisabled()
  })

  it("supports filters and pagination", async () => {
    const user = userEvent.setup()
    renderPage()

    await user.selectOptions(screen.getByLabelText("Classification"), "DEAD_STOCK")
    await user.selectOptions(screen.getByLabelText("Risk"), "CRITICAL")
    await user.selectOptions(screen.getByLabelText("Action"), "DISCOUNT")
    await user.selectOptions(screen.getByLabelText("Data status"), "LIMITED")
    await user.click(screen.getByRole("button", { name: "Next" }))

    expect(screen.getByText("Page 2")).toBeInTheDocument()
  })

  it("renders loading, empty, and API error states", () => {
    mocks.useDeadStockProducts.mockReturnValueOnce({ ...query, isLoading: true, data: undefined })
    const { rerender } = renderPage()
    expect(screen.getByLabelText("Loading dead-stock products")).toBeInTheDocument()

    mocks.useDeadStockProducts.mockReturnValueOnce({ ...query, data: { items: [], total: 0 } })
    rerender(<QueryClientProvider client={new QueryClient()}><MemoryRouter><InventoryIntelligencePage /></MemoryRouter></QueryClientProvider>)
    expect(screen.getByText("No dead-stock products match the selected filters.")).toBeInTheDocument()

    mocks.useDeadStockProducts.mockReturnValueOnce({ ...query, isError: true, data: undefined })
    rerender(<QueryClientProvider client={new QueryClient()}><MemoryRouter><InventoryIntelligencePage /></MemoryRouter></QueryClientProvider>)
    expect(screen.getByText("Dead-stock products unavailable")).toBeInTheDocument()
  })

  it("keeps the dashboard usable on mobile-sized layouts", () => {
    window.innerWidth = 390
    renderPage()
    expect(screen.getByLabelText("At-risk inventory table")).toBeInTheDocument()
    expect(screen.getByLabelText("Capital recovery simulator")).toBeInTheDocument()
  })
})
