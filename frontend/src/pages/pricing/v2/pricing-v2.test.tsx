import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ReactNode } from "react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"

import PricingOverviewPage from "./pricing-overview-page"
import PricingWorkspacePage from "./pricing-workspace-page"

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock("@/api/client", () => ({ default: api }))

beforeAll(() => {
  // Recharts' ResponsiveContainer needs ResizeObserver, which jsdom lacks.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

const PRODUCT_ID = "p-rice"
const REC_ID = "rec-1"

function renderAt(path: string, element: ReactNode, routePath: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={routePath} element={element} />
          <Route path="/app/pricing/:productId" element={<p>workspace opened</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const overviewRow = (overrides: Record<string, unknown> = {}) => ({
  product_id: PRODUCT_ID,
  title: "Rice 5kg",
  sku: null,
  category: "Grocery",
  current_price: "349.00",
  currency: "BDT",
  analytics_id: "a1",
  analytics_calculated_at: new Date().toISOString(),
  data_status: "SUFFICIENT",
  market_median_price: "320.00",
  competitor_count: 5,
  price_vs_median_rate: "0.0906",
  position: "ABOVE_MARKET",
  minimum_safe_price: "301.00",
  margin_at_risk: false,
  has_pricing_policy: true,
  recommendation: {
    id: REC_ID,
    action: "PRICE_LOWER",
    recommended_price: "329.00",
    recommendation_status: "OPEN",
    confidence_score: "55.00",
    profit_impact: "1450.00",
    generated_at: new Date().toISOString(),
    expires_at: null,
    is_actionable: true,
  },
  ...overrides,
})

function overviewPayload(items: unknown[]) {
  return {
    items,
    total: items.length,
    limit: 200,
    offset: 0,
    summary: {
      product_count: items.length,
      priced_above_market: 1,
      priced_below_market: 1,
      margin_at_risk: 0,
      recommendations_waiting: 1,
      without_analytics: 0,
      products_with_pricing_policy: 1,
      products_with_competitor_data: 2,
      last_calculated_at: new Date().toISOString(),
      position_tolerance_rate: "0.02",
    },
  }
}

describe("PricingOverviewPage", () => {
  function mockOverview(response: Promise<unknown>, feeTotal = 1) {
    api.get.mockImplementation((url: string) => {
      if (url === "/pricing/overview") return response
      if (url === "/pricing-policies/marketplace-fees") return Promise.resolve({ data: { items: [], total: feeTotal } })
      return Promise.reject(new Error(`unexpected ${url}`))
    })
  }

  it("shows a loading state", () => {
    mockOverview(new Promise(() => {}))
    renderAt("/app/pricing", <PricingOverviewPage />, "/app/pricing")
    expect(screen.getByRole("status")).toBeInTheDocument()
  })

  it("shows an error with retry", async () => {
    mockOverview(Promise.reject(new Error("Network down")))
    renderAt("/app/pricing", <PricingOverviewPage />, "/app/pricing")
    expect(await screen.findByText("Could not load pricing")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument()
  })

  it("shows an empty state with a way to add products", async () => {
    mockOverview(Promise.resolve({ data: overviewPayload([]) }))
    renderAt("/app/pricing", <PricingOverviewPage />, "/app/pricing")
    expect(await screen.findByText("No products yet")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Add products" })).toHaveAttribute("href", "/app/products/new")
  })

  it("lists products with plain-language position and suggestion, filters, and opens a product", async () => {
    const user = userEvent.setup()
    mockOverview(
      Promise.resolve({
        data: overviewPayload([
          overviewRow(),
          overviewRow({
            product_id: "p-oil",
            title: "Oil 1L",
            current_price: "180.00",
            market_median_price: "195.00",
            price_vs_median_rate: "-0.0769",
            position: "BELOW_MARKET",
            recommendation: null,
          }),
        ]),
      }),
      0,
    )
    renderAt("/app/pricing", <PricingOverviewPage />, "/app/pricing")

    const rice = (await screen.findByText("Rice 5kg")).closest("tr")!
    expect(within(rice).getByText("9% above market")).toBeInTheDocument()
    expect(within(rice).getByText("Lower price")).toBeInTheDocument()
    expect(screen.getByText("8% below market")).toBeInTheDocument()
    // No fee policies yet -> setup banner points at the first missing step.
    expect(screen.getByText("Setup 2/3 complete")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /Suggestions waiting/ }))
    expect(screen.queryByText("Oil 1L")).not.toBeInTheDocument()

    await user.click(screen.getByText("Rice 5kg"))
    expect(await screen.findByText("workspace opened")).toBeInTheDocument()
  })
})

describe("PricingWorkspacePage", () => {
  function mockWorkspace({ feeIsDefault = false, status = "OPEN" } = {}) {
    const recommendation = {
      id: REC_ID,
      action: "PRICE_LOWER",
      current_price: "349.00",
      recommended_price: "329.00",
      minimum_safe_price: "301.00",
      expected_units: "112.0000",
      expected_profit: "7840.00",
      baseline_expected_profit: "6390.00",
      profit_impact: "1450.00",
      revenue_impact: "900.00",
      margin_rate: "0.1800",
      confidence_score: "55.00",
      estimation_method: "HISTORICAL_ELASTICITY",
      recommendation_status: status,
      formula_version: "v1",
      generated_at: new Date().toISOString(),
      expires_at: null,
      evidence: {
        candidates: [
          { candidate_price: "299.00", is_allowed: false, rejection_reasons: ["BELOW_MINIMUM_SAFE_PRICE"], expected_profit: "5000.00", expected_units: "130" },
          { candidate_price: "329.00", is_allowed: true, rejection_reasons: [], expected_profit: "7840.00", expected_units: "112" },
          { candidate_price: "349.00", is_allowed: true, rejection_reasons: [], expected_profit: "6390.00", expected_units: "100" },
        ],
      },
    }
    api.get.mockImplementation((url: string) => {
      const routes: Record<string, unknown> = {
        [`/products/${PRODUCT_ID}`]: {
          id: PRODUCT_ID, seller_id: "s", title: "Rice 5kg", description: "", category: "Grocery", specifications: {},
          cost_price: "240.00", selling_price: "349.00", stock_quantity: 30, supplier_lead_time: 7, minimum_margin: "15.00",
        },
        [`/products/${PRODUCT_ID}/pricing/analytics`]: {
          item: {
            id: "a1", current_price: "349.00", unit_cost: "240.00", percentage_fee_rate: "0.135", fixed_fee_amount: "0.00",
            current_unit_profit: "61.90", current_margin_rate: "0.1774", minimum_safe_price: "301.00",
            competitor_min_price: "299.00", competitor_q1_price: "310.00", competitor_median_price: "320.00",
            competitor_q3_price: "335.00", competitor_max_price: "360.00", competitor_count: 5, in_stock_competitor_count: 3,
            data_status: "SUFFICIENT", confidence_score: "80.00", calculation_version: "v2",
            calculated_at: new Date().toISOString(), evidence: {},
          },
        },
        [`/products/${PRODUCT_ID}/pricing/analytics/history`]: { items: [] },
        [`/products/${PRODUCT_ID}/pricing/recommendations/latest`]: { item: recommendation },
        [`/pricing-policies/products/${PRODUCT_ID}`]: {
          is_default: false, minimum_margin_rate: "0.15", minimum_unit_profit: "0.00", maximum_price_decrease_rate: "0.10",
          maximum_price_increase_rate: "0.10", minimum_allowed_price: null, maximum_allowed_price: null, price_increment: "5.00",
        },
        "/recommendation-outcomes/track-record": {
          enabled: true, days: 60, min_outcomes: 20, outcomes: 30, hit_rate: 0.7, reliable: true,
          bands: { LOW: { outcomes: 2, hit_rate: 0.5, reliable: false }, MEDIUM: { outcomes: 24, hit_rate: 0.6667, reliable: true }, HIGH: { outcomes: 4, hit_rate: 1, reliable: false } },
        },
        [`/pricing-policies/products/${PRODUCT_ID}/fees/effective`]: {
          id: feeIsDefault ? null : "fee-1", seller_id: "s", product_id: null, marketplace: "Daraz Bangladesh", category: null,
          currency: "BDT", percentage_commission_rate: "0.12", payment_fee_rate: "0.015", fixed_per_order_fee: "0",
          fixed_per_unit_fee: "0", fulfilment_fee: "0", shipping_subsidy: "0", other_variable_cost: "0", effective_from: null,
          effective_to: null, source: "MANUAL", version: "v1", is_active: true, is_default: feeIsDefault, scope: "MARKETPLACE",
        },
      }
      return url in routes ? Promise.resolve({ data: routes[url] }) : Promise.reject(new Error(`unexpected ${url}`))
    })
    api.post.mockImplementation((url: string) => {
      if (url === `/products/${PRODUCT_ID}/pricing/simulate`) {
        return Promise.resolve({
          data: {
            seller_id: "s", product_id: PRODUCT_ID, product_title: "Rice 5kg", pricing_analytics_id: "a1", current_price: "349.00",
            baseline_units: "100", baseline_expected_revenue: "34900", baseline_expected_profit: "6190", forecast_horizon_days: 30,
            demand_method: "HISTORICAL_ELASTICITY", data_status: "SUFFICIENT", confidence_score: "70", calculated_at: new Date().toISOString(),
            evidence: { elasticity: "-0.9" },
            scenarios: [{
              candidate_price: "350.00", action: "HOLD", is_allowed: true, rejection_reasons: [], expected_units_lower: "90",
              expected_units: "100", expected_units_upper: "110", expected_revenue: "35000.00", expected_profit: "6200.00",
              revenue_impact: "100", profit_impact: "10", unit_profit: "62", margin_rate: "0.1771", minimum_safe_price: "301.00",
              confidence_score: "70", estimation_method: "HISTORICAL_ELASTICITY", data_status: "SUFFICIENT", evidence: {},
            }],
          },
        })
      }
      const decision = /\/pricing\/recommendations\/(.+)\/(acknowledge|dismiss)$/.exec(url)
      if (decision) {
        return Promise.resolve({
          data: { ...recommendation, recommendation_status: decision[2] === "acknowledge" ? "ACKNOWLEDGED" : "DISMISSED" },
        })
      }
      return Promise.reject(new Error(`unexpected POST ${url}`))
    })
  }

  const open = () =>
    renderAt(`/app/pricing/${PRODUCT_ID}`, <PricingWorkspacePage />, "/app/pricing/:productId")

  it("shows the recommendation and records 'Mark as applied' without changing the price", async () => {
    const user = userEvent.setup()
    mockWorkspace()
    open()

    expect(await screen.findByText("Lower to BDT 329 (from BDT 349)")).toBeInTheDocument()
    // Confidence 55 is the MEDIUM band, which has a measured hit rate.
    expect(await screen.findByText(/Confidence: Medium · right 67% of the time/)).toBeInTheDocument()
    expect(screen.getByText(/Change it on Daraz yourself/)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Mark as applied" }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/pricing/recommendations/${REC_ID}/acknowledge`))
    expect(await screen.findByText(/Marked as applied/)).toBeInTheDocument()
    expect(api.post.mock.calls.map(([url]) => url).filter((url: string) => url.includes("products/") && !url.endsWith("/simulate"))).toEqual([])
  })

  it("dismisses a recommendation", async () => {
    const user = userEvent.setup()
    mockWorkspace()
    open()

    await user.click(await screen.findByRole("button", { name: "Dismiss" }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/pricing/recommendations/${REC_ID}/dismiss`))
    expect(await screen.findByText(/Dismissed\./)).toBeInTheDocument()
  })

  it("labels where the simulator's demand estimate comes from", async () => {
    mockWorkspace()
    open()

    expect(await screen.findByTestId("elasticity-source")).toHaveTextContent("Using your sales history (elasticity −0.9)")
    expect(api.post).toHaveBeenCalledWith(`/products/${PRODUCT_ID}/pricing/simulate`, expect.anything())
    expect(screen.getByRole("slider")).toHaveAttribute("step", "500")
  })

  it("asks for marketplace fees instead of suggesting a price when none are set", async () => {
    mockWorkspace({ feeIsDefault: true })
    open()

    expect(await screen.findByText("Marketplace fee data is missing.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Mark as applied" })).not.toBeInTheDocument()
  })
})
