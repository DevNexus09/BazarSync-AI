import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import type { PropsWithChildren } from "react"
import { describe, expect, it, vi } from "vitest"

import { useLiveDashboard } from "./useLiveDashboard"

const events = vi.hoisted(() => new Map<string, (event: unknown) => void>())
vi.mock("@/hooks/useRealtime", () => ({ useRealtime: () => ({ status: {} }) }))
vi.mock("@/hooks/useSocketEvent", () => ({
  useSocketEvent: (event: string, handler: (event: unknown) => void) => events.set(event, handler),
}))

describe("recommendation explanation refresh", () => {
  it("refreshes the authenticated seller's saved results after final delivery", async () => {
    const client = new QueryClient()
    const current = ["recommendations", "seller-a", "product-a"]
    const job = ["recommendation-job", "seller-a", "product-a", "job-a"]
    const foreign = ["recommendations", "seller-b", "product-b"]
    for (const key of [current, job, foreign]) client.setQueryData(key, { saved: true })
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    renderHook(() => useLiveDashboard({ sellerId: "seller-a" }), { wrapper })
    act(() => events.get("recommendation_created")?.({
      eventId: "final-explanation",
      payload: { confidence: "LOW", recommendation: {
        id: "record-a", product: "Tea", summary: "যাচাই করা পরামর্শ", createdAt: "2026-11-19T10:00:00Z",
      } },
    }))
    await waitFor(() => expect(client.getQueryState(current)?.isInvalidated).toBe(true))
    expect(client.getQueryState(job)?.isInvalidated).toBe(true)
    expect(client.getQueryState(foreign)?.isInvalidated).toBe(false)
  })
})
