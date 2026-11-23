import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { TrackRecordLine } from "./TrackRecordLine"

const api = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock("@/api/client", () => ({ default: api }))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

const band = (outcomes: number, hit_rate: number | null) => ({ outcomes, hit_rate, reliable: outcomes >= 20 })

function renderWith(data: unknown) {
  api.get.mockResolvedValue({ data })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TrackRecordLine type="REORDER" />
    </QueryClientProvider>,
  )
}

describe("TrackRecordLine", () => {
  it("states the measured hit rate once there are enough outcomes", async () => {
    renderWith({ enabled: true, days: 60, min_outcomes: 20, ...band(25, 0.82), bands: { LOW: band(0, null), MEDIUM: band(5, 0.6), HIGH: band(20, 0.875) } })
    expect(await screen.findByText("Track record: our reorder dates were right 82% of the time in the last 60 days (25 orders checked).")).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith("/recommendation-outcomes/track-record", { params: { recommendation_type: "REORDER" } })
  })

  it("stays hidden with fewer than the minimum outcomes", async () => {
    renderWith({ enabled: true, days: 60, min_outcomes: 20, ...band(19, 0.9), bands: {} })
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    expect(screen.queryByText(/Track record/)).not.toBeInTheDocument()
  })

  it("stays hidden when outcome tracking is off", async () => {
    renderWith({ enabled: false, recommendation_type: "REORDER" })
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    expect(screen.queryByText(/Track record/)).not.toBeInTheDocument()
  })
})
