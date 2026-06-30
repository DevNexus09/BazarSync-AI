import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { usePhase5RealtimeInvalidation } from "@/hooks/usePhase5RealtimeInvalidation"

const listeners = new Map<string, (payload?: unknown) => void>()
const ioListeners = new Map<string, () => void>()

vi.mock("@/hooks/useSocketEvent", () => ({
  useSocketEvent: (
    event: string,
    handler: (payload?: unknown) => void,
    options?: { enabled?: boolean }
  ) => {
    if (options?.enabled !== false) {
      listeners.set(event, handler)
    }
  },
}))

vi.mock("@/lib/socket", () => ({
  getSocket: () => ({
    on: (event: string, handler: () => void) => listeners.set(event, handler),
    off: (event: string) => listeners.delete(event),
    io: {
      on: (event: string, handler: () => void) => ioListeners.set(event, handler),
      off: (event: string) => ioListeners.delete(event),
    },
  }),
}))

function Harness({
  productId = "product-1",
}: {
  productId?: string
}) {
  usePhase5RealtimeInvalidation({
    sellerId: "seller-1",
    productId,
    accessibleProductIds: ["product-1"],
  })
  return null
}

function renderHookHarness(queryClient = new QueryClient()) {
  render(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>
  )
  return queryClient
}

afterEach(() => {
  listeners.clear()
  ioListeners.clear()
})

describe("usePhase5RealtimeInvalidation", () => {
  it("invalidates Phase 5 queries for valid accessible socket events", () => {
    const queryClient = renderHookHarness()
    const invalidate = vi.spyOn(queryClient, "invalidateQueries")

    listeners.get("competitor.event.created")?.({
      version: 1,
      event: "competitor.event.created",
      seller_id: "seller-1",
      product_id: "product-1",
      occurred_at: "2026-06-29T12:00:00Z",
      data: { event_id: "event-1" },
    })

    expect(invalidate).toHaveBeenCalled()
  })

  it("ignores inaccessible products and duplicate events", () => {
    const queryClient = renderHookHarness()
    const invalidate = vi.spyOn(queryClient, "invalidateQueries")

    const validPayload = {
      version: 1,
      event: "competitor.event.created",
      seller_id: "seller-1",
      product_id: "product-1",
      occurred_at: "2026-06-29T12:00:00Z",
      data: { event_id: "event-1" },
    }
    listeners.get("competitor.event.created")?.({
      ...validPayload,
      product_id: "product-2",
    })
    listeners.get("competitor.event.created")?.(validPayload)
    listeners.get("competitor.event.created")?.(validPayload)

    expect(invalidate).toHaveBeenCalledTimes(2)
  })

  it("refetches Phase 5 data after reconnect and cleans listeners on unmount", () => {
    const queryClient = new QueryClient()
    const invalidate = vi.spyOn(queryClient, "invalidateQueries")
    const { unmount } = render(
      <QueryClientProvider client={queryClient}>
        <Harness />
      </QueryClientProvider>
    )

    ioListeners.get("reconnect")?.()

    expect(invalidate).toHaveBeenCalled()
    expect(ioListeners.has("reconnect")).toBe(true)

    unmount()

    expect(ioListeners.has("reconnect")).toBe(false)
  })
})
