import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router-dom"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"

import InventoryIntelligenceV2Page from "./inventory-intelligence-v2-page"
import { UNDO_MS } from "./use-reorder-decisions"

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock("@/api/client", () => ({ default: api }))

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.useRealTimers()
})

const iso = (offsetDays: number) => new Date(Date.now() + offsetDays * 86_400_000).toISOString().slice(0, 10)

const row = (overrides: Record<string, unknown>) => ({
  product_id: "p",
  product_name: "Product",
  category: "Grocery",
  risk_level: "MEDIUM",
  risk_score: "50",
  data_status: "SUFFICIENT",
  days_remaining: "30",
  predicted_stockout_date: null,
  reorder_action: "HOLD",
  recommendation_status: "OPEN",
  recommended_quantity: 0,
  reorder_deadline: null,
  calculation_version: "v1",
  as_of_date: iso(0),
  last_updated_at: new Date().toISOString(),
  reorder_recommendation_id: null,
  supplier_lead_time_days: 7,
  supplier_lead_time_defaulted: false,
  ...overrides,
})

const RISKS = [
  row({ product_id: "p-flour", product_name: "Flour 2kg", days_remaining: "40" }),
  row({ product_id: "p-oil", product_name: "Oil 1L", risk_level: "HIGH", days_remaining: "3", supplier_lead_time_days: 8, reorder_action: "REORDER", recommended_quantity: 150, reorder_deadline: iso(0), reorder_recommendation_id: "rec-oil" }),
  row({ product_id: "p-rice", product_name: "Rice 5kg", risk_level: "CRITICAL", days_remaining: "0", reorder_action: "REORDER", recommended_quantity: 60, reorder_recommendation_id: "rec-rice", supplier_lead_time_defaulted: true }),
]

function mockApi() {
  api.get.mockImplementation((url: string) => {
    const routes: Record<string, unknown> = {
      "/inventory-intelligence/summary": {
        total_active_products: 3, low_risk_products: 1, medium_risk_products: 0, high_risk_products: 1, critical_risk_products: 1,
        insufficient_data_products: 0, products_requiring_reorder: 2, products_already_out_of_stock: 1,
        last_calculation_time: new Date().toISOString(), data_freshness_status: "FRESH",
      },
      "/inventory-intelligence/risks": { items: RISKS, total: RISKS.length, limit: 200, offset: 0 },
      "/dead-stock/summary": { total_locked_capital: "84000", locked_capital_currency: "BDT", monetary_totals_comparable: true, age_distribution: {} },
      "/dead-stock/products": { items: [], total: 0, limit: 200, offset: 0 },
      "/inventory-intelligence/products/p-oil": {
        product_id: "p-oil", product_name: "Oil 1L", quantity_on_hand: 30, quantity_reserved: 6, quantity_available: 24, quantity_incoming: 12,
        daily_sales_rate: "8", days_remaining: "3", risk_level: "HIGH", reorder_action: "REORDER", recommended_quantity: 150,
        reorder_deadline: iso(0), supplier_lead_time_days: 8, safety_buffer_days: 3, reorder_recommendation_id: "rec-oil", recommendation_status: "OPEN",
        calculation_version: "v1", metadata: {}, supplier_lead_time_defaulted: true, safety_stock_units: 18, safety_stock_service_level: "0.95",
      },
      "/products/p-oil/inventory-history": { items: [] },
    }
    return url in routes ? Promise.resolve({ data: routes[url] }) : Promise.reject(new Error(`unexpected ${url}`))
  })
  api.post.mockResolvedValue({ data: {} })
}

function Location() {
  return <output data-testid="location">{useLocation().search}</output>
}

function renderPage(path = "/app/inventory-intelligence") {
  mockApi()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <InventoryIntelligenceV2Page />
        <Location />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("InventoryIntelligenceV2Page", () => {
  it("opens on Today with a ranked to-do list and a data health line", async () => {
    renderPage()
    const list = await screen.findByRole("list")
    expect(within(list).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      expect.stringContaining("Rice 5kg is out of stock — order 60"),
      expect.stringContaining("Reorder Oil 1L — runs out in 3 days, lead time 8 days"),
    ])
    expect(screen.getByText("1 product has no supplier lead time, so reorder dates are estimates.")).toBeInTheDocument()
    expect(screen.queryByText(/calculation version|v1/i)).not.toBeInTheDocument()
  })

  it("deep-links to a tab and product drawer, and Esc closes the drawer", async () => {
    const user = userEvent.setup()
    renderPage("/app/inventory-intelligence?tab=reorder&product=p-oil")
    const dialog = await screen.findByRole("dialog", { name: "Oil 1L" })
    expect(await within(dialog).findByText("Order 150 units by " + new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${iso(0)}T00:00:00Z`)))).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Reorder", hidden: true })).toHaveAttribute("aria-selected", "true")
    expect(within(dialog).getByText(/buffer of 18 units \(95% protection\)/)).toBeInTheDocument()
    expect(within(dialog).getByText("Supplier lead time missing")).toBeInTheDocument()

    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(screen.getByTestId("location").textContent).toBe("?tab=reorder")
  })

  it("opens the drawer from a row and returns focus to it on close", async () => {
    const user = userEvent.setup()
    renderPage("/app/inventory-intelligence?tab=reorder")
    const oilRow = (await screen.findByText("Oil 1L")).closest("tr")!
    await user.click(oilRow)
    const dialog = await screen.findByRole("dialog", { name: "Oil 1L" })
    expect(dialog).toContainElement(document.activeElement as HTMLElement)

    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(oilRow).toHaveFocus()
  })

  it("marks a reorder as ordered optimistically, and Undo cancels the call", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderPage("/app/inventory-intelligence?tab=reorder")
    const oilRow = (await screen.findByText("Oil 1L")).closest("tr")!

    await user.click(within(oilRow).getByRole("button", { name: "Ordered ✓" }))
    expect(within(oilRow).queryByRole("button", { name: "Ordered ✓" })).not.toBeInTheDocument()
    expect(screen.getByText("Marked Oil 1L as ordered")).toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Undo" }))
    act(() => vi.advanceTimersByTime(UNDO_MS + 500))
    expect(within(oilRow).getByRole("button", { name: "Ordered ✓" })).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it("sends mark-ordered once the undo window passes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderPage("/app/inventory-intelligence?tab=reorder")
    const oilRow = (await screen.findByText("Oil 1L")).closest("tr")!

    await user.click(within(oilRow).getByRole("button", { name: "Ordered ✓" }))
    expect(api.post).not.toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(UNDO_MS + 10))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/reorder-recommendations/rec-oil/mark-ordered"))
    expect(api.post).toHaveBeenCalledTimes(1)
  })
})
