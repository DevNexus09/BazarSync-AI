import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AxiosError } from "axios"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import apiClient from "@/api/client"

import RecommendationDashboardPage from "./RecommendationDashboardPage"
import type { RecommendationApiResponse } from "./types/recommendation"

const logout = vi.hoisted(() => vi.fn())
const productsState = vi.hoisted(() => ({ error: undefined as unknown }))
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ user: { id: "seller-a" }, logout }) }))
vi.mock("@/hooks/use-products", () => ({
  useProducts: () => productsState.error
    ? { data: undefined, isError: true, error: productsState.error }
    : { data: [{ id: "product-a", title: "Tea", category: "Food" }] },
}))

const legacy: RecommendationApiResponse = {
  success: true,
  product_id: "product-a",
  created_at: "2026-11-17T11:00:00Z",
  recommendation: { action: "HOLD", confidence: "LOW", reasoning_bn: "বর্তমান দাম রাখুন", revenue_opportunity: 250 },
  analytics: {
    competitor_median_price: "435",
    price_gap_percent: null,
    stock_risk_score: 0,
    stock_risk_available: false,
    pricing_pressure_score: 0,
    estimated_days_of_stock_left: 0,
  },
}
const enhanced: RecommendationApiResponse = {
  ...legacy,
  dashboard_evidence: {
    competitor_observed_at: "2026-11-16T11:00:00Z",
    competitor_freshness: "STALE",
    available_units: "0",
    reason_codes: ["SALES_HISTORY_UNAVAILABLE"],
    insufficient_evidence: true,
    price_blocked: true,
    supporting_actions: [{ action: "LISTING_IMPROVEMENT", source: "dead_stock_recovery" }],
    pricing_candidates: [{ price: "400", constraints_passed: false, rejection_reasons: ["BELOW_MINIMUM_MARGIN"] }],
    forecasts: [
      { horizon_days: 7, expected_units: "0", method: "catboost", version: "approved-v1", source: "active",
        data_cutoff: "2026-11-16T11:00:00Z", uncertainty: "calibrated", prediction_interval: ["0", "3"] },
      { horizon_days: 30, expected_units: "8", method: "catboost", version: "previous-v1", source: "previous",
        data_cutoff: "2026-11-16T11:00:00Z", uncertainty: "empirical_unvalidated", prediction_interval: ["1", "19"] },
    ],
    reorder: { quantity: 4, deadline: "2026-11-20", lead_time_demand: "2", demand_source: "recorded_sales_velocity" },
  },
}

function apiError(status: number) {
  return Object.assign(new AxiosError("Request failed"), { response: { status } })
}

function mount() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { gcTime: 0 } } })}>
      <MemoryRouter initialEntries={["/app/recommendations"]}>
        <RecommendationDashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("recommendations dashboard", () => {
  beforeEach(() => {
    productsState.error = undefined
    vi.stubEnv("VITE_RECOMMENDATION_DASHBOARD_V2", "true")
    const storage = new Map<string, string>()
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
    })
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it("renders old records against a backend without durable discovery or v2 fields", async () => {
    vi.spyOn(apiClient, "get").mockImplementation(async (path) => {
      if (path.endsWith("/job")) throw apiError(404)
      return { data: legacy }
    })
    mount()
    expect(await screen.findByText(legacy.recommendation.reasoning_bn)).toHaveAttribute("lang", "bn")
    expect(screen.getByText("LOW confidence")).toBeVisible()
    expect(screen.getByText("Legacy heuristic estimate.")).toBeVisible()
    expect(screen.queryByRole("heading", { name: "Demand forecast" })).not.toBeInTheDocument()
    expect(screen.getByText("Generation status: Completed")).toBeVisible()
  })

  it("shows a loading state then the empty history state", async () => {
    let rejectLatest: (reason: unknown) => void = () => undefined
    vi.spyOn(apiClient, "get").mockImplementation((path) => {
      if (path.endsWith("/job")) return Promise.reject(apiError(404))
      return new Promise((_resolve, reject) => { rejectLatest = reject })
    })
    mount()
    expect(screen.getByRole("status", { name: "Loading recommendation" })).toBeVisible()
    rejectLatest(apiError(404))
    expect(await screen.findByText("No AI recommendation yet")).toBeVisible()
    expect(screen.getByText("Generation status: Not generated")).toBeVisible()
  })

  it("shows a load error and recovers through retry", async () => {
    const get = vi.spyOn(apiClient, "get").mockImplementation(async (path) => {
      throw apiError(path.endsWith("/job") ? 404 : 503)
    })
    mount()
    const retry = await screen.findByRole("button", { name: "Retry loading" }, { timeout: 2500 })
    expect(screen.getByRole("alert")).toBeVisible()
    get.mockImplementation(async (path) => {
      if (path.endsWith("/job")) throw apiError(404)
      return { data: legacy }
    })
    await userEvent.click(retry)
    expect(await screen.findByText(legacy.recommendation.reasoning_bn)).toBeVisible()
  })

  it("renders evidence, missing horizons and advisory comparisons from a completed job", async () => {
    vi.spyOn(apiClient, "get").mockImplementation(async (path) => {
      if (path.endsWith("/job")) return { data: {
        job_id: "job-a", product_id: "product-a", status: "COMPLETED", result: enhanced,
      } }
      throw apiError(404)
    })
    mount()
    expect(await screen.findByText("Generation status: Insufficient evidence")).toBeVisible()
    expect(screen.getByText(/low-confidence recommendation/)).toBeVisible()
    expect(screen.getByText(/Sales history is missing/)).toBeVisible()
    expect(screen.getByText(/Competitor data was stale/)).toBeVisible()
    expect(screen.getByText(/MarginGuard blocked/)).toBeVisible()
    expect(screen.getByText("Last evidence update")).toBeVisible()
    const forecast = screen.getByRole("region", { name: "Demand forecast" })
    expect(within(forecast).getByText("0 units")).toBeVisible()
    expect(within(forecast).getByText("14-day demand").nextElementSibling).toHaveTextContent("Unavailable")
    expect(within(forecast).getByText("Calibrated interval 0–3 units")).toBeVisible()
    expect(within(forecast).getByText("Calibrated interval unavailable")).toBeVisible()
    expect(screen.getByRole("region", { name: "Reorder insights" })).toHaveTextContent("Heuristic estimate")
    expect(screen.getByRole("region", { name: "Supporting recommendations" })).toHaveTextContent("listing improvement")
    const comparison = screen.getByText("Pricing candidate comparison")
    comparison.focus()
    expect(comparison).toHaveFocus()
    await userEvent.click(comparison)
    expect(screen.getByText("Below the minimum margin.")).toBeVisible()
  })

  it("generates via the durable endpoint and announces queued then processing", async () => {
    vi.spyOn(apiClient, "get").mockImplementation(async (path) => {
      if (!path.endsWith("/jobs/job-a")) throw apiError(404)
      return { data: { job_id: "job-a", product_id: "product-a", status: "RUNNING", result: null } }
    })
    let submit: (response: unknown) => void = () => undefined
    const post = vi.spyOn(apiClient, "post").mockImplementation(() => new Promise((resolve) => { submit = resolve }))
    mount()
    await screen.findByText("Generation status: Not generated")
    await userEvent.click(screen.getAllByRole("button", { name: "Generate AI Recommendation" })[0])
    expect(screen.getByText("Generation status: Queued")).toBeVisible()
    expect(post).toHaveBeenCalledWith(
      "/recommendations/generate/product-a",
      undefined,
      { headers: { "Idempotency-Key": expect.any(String) } },
    )
    submit({ data: { success: true, status: "processing", product_id: "product-a", task_id: "job-a", job_id: "job-a" } })
    expect(await screen.findByText("Generation status: Processing")).toBeVisible()
    expect(screen.getByRole("button", { name: "Generating" })).toBeDisabled()
  })

  it("labels missing forecasts and uses a stacked layout below the small breakpoint", async () => {
    vi.spyOn(apiClient, "get").mockImplementation(async (path) => {
      if (path.endsWith("/job")) throw apiError(404)
      return { data: { ...enhanced, dashboard_evidence: {} } }
    })
    vi.stubGlobal("innerWidth", 375)
    try {
      mount()
      const forecast = await screen.findByRole("region", { name: "Demand forecast" })
      expect(within(forecast).getByText(/No approved forecasting model/)).toBeVisible()
      const list = forecast.querySelector("dl")
      expect(list).toHaveClass("grid", "sm:grid-cols-3")
      expect(list?.className).not.toMatch(/(?:^|\s)grid-cols-[2-9]/)
      expect(within(forecast).getAllByText("Unavailable")).toHaveLength(3)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it("preserves the primary card with the flag off or optional evidence malformed", async () => {
    vi.spyOn(apiClient, "get").mockImplementation(async (path) => {
      if (path.endsWith("/job")) throw apiError(404)
      return { data: enhanced }
    })
    vi.stubEnv("VITE_RECOMMENDATION_DASHBOARD_V2", "false")
    const view = mount()
    expect(await screen.findByText(legacy.recommendation.reasoning_bn)).toBeVisible()
    expect(screen.queryByRole("heading", { name: "Demand forecast" })).not.toBeInTheDocument()
    view.unmount()
    vi.stubEnv("VITE_RECOMMENDATION_DASHBOARD_V2", "true")
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path.endsWith("/job")) throw apiError(404)
      return { data: { ...legacy, dashboard_evidence: { forecasts: [{ expected_units: "" }] } } }
    })
    mount()
    expect(await screen.findByText(legacy.recommendation.reasoning_bn)).toBeVisible()
    expect(screen.queryByRole("heading", { name: "Demand forecast" })).not.toBeInTheDocument()
  })

  it("handles an expired session before product discovery", async () => {
    productsState.error = apiError(401)
    const get = vi.spyOn(apiClient, "get")
    mount()
    expect(screen.getByRole("alert")).toHaveTextContent("Your session has expired")
    expect(get).not.toHaveBeenCalled()
    expect(screen.queryByRole("button", { name: /Generate AI Recommendation/i })).not.toBeInTheDocument()
  })

  it("offers sign-in and hides generation after an expired seller session", async () => {
    const get = vi.spyOn(apiClient, "get").mockRejectedValue(apiError(401))
    const post = vi.spyOn(apiClient, "post")
    mount()
    expect(await screen.findByRole("alert")).toHaveTextContent("Your session has expired")
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login")
    expect(screen.queryByRole("button", { name: /Generate AI Recommendation/i })).not.toBeInTheDocument()
    expect(get.mock.calls.length).toBeLessThanOrEqual(2)
    expect(post).not.toHaveBeenCalled()
  })
})
