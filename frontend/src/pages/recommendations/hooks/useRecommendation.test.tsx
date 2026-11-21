import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import type { PropsWithChildren } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useRecommendation } from "./useRecommendation"
import { generateRecommendation, getLatestRecommendation, getRecommendationJob } from "../services/recommendationApi"
import type { RecommendationData } from "../types/recommendation"

vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ user: { id: "seller-a" } }) }))
vi.mock("../services/recommendationApi", () => ({
  generateRecommendation: vi.fn(),
  getLatestRecommendation: vi.fn(),
  getRecommendationJob: vi.fn(),
}))

const productId = "product-a"
const result: RecommendationData = {
  success: true,
  productId,
  createdAt: "2026-11-14T10:00:00Z",
  recommendation: { action: "HOLD", confidence: "LOW", reasoningBn: "বর্তমান দাম রাখুন", revenueOpportunity: 0 },
  analytics: { competitorMedianPrice: 100, priceGapPercent: null, stockRiskScore: 0, pricingPressureScore: 0, estimatedDaysOfStockLeft: 0 },
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { ...renderHook(() => useRecommendation(productId), { wrapper }), client }
}

describe("durable recommendation polling", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    const storage = new Map<string, string>()
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
    })
    vi.mocked(getLatestRecommendation).mockResolvedValue(null)
  })
  afterEach(() => vi.unstubAllGlobals())

  it("replays an unresolved submission key even if discovery returns an older job", async () => {
    window.localStorage.setItem(
      "recommendation-job:seller-a:product-a",
      JSON.stringify({ requestKey: "lost-response-key" }),
    )
    vi.mocked(getRecommendationJob).mockResolvedValue({
      jobId: "older-job", productId, status: "COMPLETED", result, errorMessage: null,
    })
    vi.mocked(generateRecommendation).mockResolvedValue({
      queued: true, productId, taskId: "replayed-job", jobId: "replayed-job",
    })
    const view = mount()
    await waitFor(() => expect(view.result.current.data).toEqual(result))
    act(() => view.result.current.generateRecommendation())
    await waitFor(() => expect(generateRecommendation).toHaveBeenCalledWith(productId, "lost-response-key"))
  })

  it("coalesces double clicks and restores the exact completed result on reload", async () => {
    vi.mocked(getRecommendationJob).mockImplementation(async (_product, id) => id
      ? { jobId: id, productId, status: "COMPLETED", result, errorMessage: null }
      : null)
    vi.mocked(generateRecommendation).mockResolvedValue({
      queued: true, productId, taskId: "job-a", jobId: "job-a",
    })
    const view = mount()
    await waitFor(() => expect(view.result.current.isLoading).toBe(false))
    act(() => {
      view.result.current.generateRecommendation()
      view.result.current.generateRecommendation()
    })
    await waitFor(() => expect(view.result.current.data).toEqual(result))
    expect(generateRecommendation).toHaveBeenCalledTimes(1)
    expect(getRecommendationJob).toHaveBeenLastCalledWith(productId, "job-a")
    expect(view.result.current.isGenerating).toBe(false)
    view.unmount()
    const reloaded = mount()
    await waitFor(() => expect(reloaded.result.current.data).toEqual(result))
    expect(getRecommendationJob).toHaveBeenLastCalledWith(productId, "job-a")
  })

  it("shows a refreshed explanation for the same saved recommendation", async () => {
    vi.mocked(getRecommendationJob).mockResolvedValue({
      jobId: "job-a", productId, status: "COMPLETED", result, errorMessage: null,
    })
    const view = mount()
    await waitFor(() => expect(view.result.current.data).toEqual(result))
    const enhanced = {
      ...result,
      recommendation: { ...result.recommendation, reasoningBn: "যাচাই করা তথ্যের ভিত্তিতে বর্তমান দাম বজায় রাখুন।" },
    }
    act(() => view.client.setQueryData(
      ["recommendations", "seller-a", productId],
      enhanced,
      { updatedAt: Date.now() + 10 },
    ))
    await waitFor(() => expect(view.result.current.data?.recommendation.reasoningBn).toBe(enhanced.recommendation.reasoningBn))
    expect(view.result.current.isQueued).toBe(false)
  })

  it("polls running jobs and stops at failure with a new key on retry", async () => {
    vi.mocked(getRecommendationJob)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({ jobId: "job-a", productId, status: "RUNNING", result: null, errorMessage: null })
      .mockResolvedValue({ jobId: "job-a", productId, status: "FAILED", result: null, errorMessage: "Please retry." })
    vi.mocked(generateRecommendation).mockResolvedValue({
      queued: true, productId, taskId: "job-a", jobId: "job-a",
    })
    const view = mount()
    await waitFor(() => expect(view.result.current.isLoading).toBe(false))
    act(() => view.result.current.generateRecommendation())
    await waitFor(() => expect(view.result.current.jobStatus).toBe("RUNNING"))
    await waitFor(() => expect(view.result.current.errorMessage).toBe("Please retry."), { timeout: 3500 })
    expect(view.result.current.isGenerating).toBe(false)
    const calls = vi.mocked(getRecommendationJob).mock.calls.length
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 2200)) })
    expect(getRecommendationJob).toHaveBeenCalledTimes(calls)
    act(() => view.result.current.generateRecommendation())
    await waitFor(() => expect(generateRecommendation).toHaveBeenCalledTimes(2))
    expect(vi.mocked(generateRecommendation).mock.calls[0][1])
      .not.toBe(vi.mocked(generateRecommendation).mock.calls[1][1])
  }, 10_000)
})
