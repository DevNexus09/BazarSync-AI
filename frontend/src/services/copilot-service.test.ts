import { beforeEach, describe, expect, it, vi } from "vitest"

import apiClient from "@/api/client"

import { askCopilot } from "./copilot-service"

vi.mock("@/api/client", () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
  },
}))

describe("copilot service", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(apiClient.post).mockResolvedValue({
      data: {
        conversation_id: "conversation-1",
        message_id: "message-1",
        answer: "Answer",
        summary: "Summary",
        confidence: "HIGH",
        language: "en",
        intent: "UNKNOWN",
        tools_used: [],
        evidence: [],
        missing_data: [],
        data_freshness: [],
        recommended_next_steps: [],
        action_proposal: null,
      },
    })
  })

  it("posts the backend CopilotAskRequest contract without deprecated source_types", async () => {
    await askCopilot({
      conversation_id: "conversation-1",
      question: "What changed?",
      product_id: null,
      from_date: "2026-07-01",
      to_date: "2026-07-12",
      domain_filters: ["SALES_REVENUE", "COMPETITOR"],
      language: "auto",
      include_current_data: false,
      include_memory: true,
      memory_source_types: ["SALES_HISTORY"],
      top_k: 5,
    })

    expect(apiClient.post).toHaveBeenCalledWith(
      "/copilot/ask",
      expect.objectContaining({
        conversation_id: "conversation-1",
        question: "What changed?",
        from_date: "2026-07-01",
        to_date: "2026-07-12",
        domain_filters: ["SALES_REVENUE", "COMPETITOR"],
        include_current_data: false,
        include_memory: true,
        memory_source_types: ["SALES_HISTORY"],
        top_k: 5,
      })
    )
    expect(apiClient.post).toHaveBeenCalledWith(
      "/copilot/ask",
      expect.not.objectContaining({
        source_types: expect.anything(),
        product_id: expect.anything(),
      })
    )
  })
})
