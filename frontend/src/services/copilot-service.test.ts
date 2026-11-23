import { beforeEach, describe, expect, it, vi } from "vitest"

import apiClient from "@/api/client"

import { askCopilot, askCopilotStream, getCopilotFeatures, submitCopilotFeedback } from "./copilot-service"

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

  it("sends no filters: only the question, conversation and language, with data and memory on", async () => {
    await askCopilot({ conversation_id: "conversation-1", question: "What changed?", language: "bn" })

    expect(apiClient.post).toHaveBeenCalledWith("/copilot/ask", {
      conversation_id: "conversation-1",
      question: "What changed?",
      language: "bn",
      include_current_data: true,
      include_memory: true,
    })
  })

  it("defaults language to auto and omits a missing conversation id", async () => {
    await askCopilot({ question: "Revenue for 2026-10-01 to 2026-10-31?" })

    expect(apiClient.post).toHaveBeenCalledWith("/copilot/ask", {
      question: "Revenue for 2026-10-01 to 2026-10-31?",
      language: "auto",
      include_current_data: true,
      include_memory: true,
    })
  })

  it("posts feedback for an assistant message", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: { message_id: "m1", rating: "down" } })

    await submitCopilotFeedback("m1", "down")

    expect(apiClient.post).toHaveBeenCalledWith("/copilot/messages/m1/feedback", { rating: "down" })
  })

  it("reads feature switches from the real capabilities response shape", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: {
        status: "ok",
        capabilities: {
          features: { multilingual: true, languages: ["auto", "en", "bn", "banglish"], streaming: false, follow_ups: true, feedback: true, conversation_memory: false },
          metrics: {},
        },
      },
    })
    expect(await getCopilotFeatures()).toMatchObject({ multilingual: true, languages: ["auto", "en", "bn", "banglish"], follow_ups: true })
    expect(apiClient.get).toHaveBeenCalledWith("/copilot/capabilities")
  })

  it("falls back to safe defaults when features are missing", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { status: "ok", capabilities: {} } })
    expect(await getCopilotFeatures()).toMatchObject({ streaming: false, multilingual: false, languages: ["auto", "en", "bn"] })
  })
})

function sseResponse(chunks: string[], init: { status?: number } = {}) {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
      controller.close()
    },
  })
  return new Response(body, { status: init.status ?? 200, headers: { "Content-Type": "text/event-stream" } })
}

describe("copilot streaming client", () => {
  const answer = {
    conversation_id: "c1",
    message_id: "m1",
    answer: "Answer",
    confidence: "HIGH",
    language: "en",
    missing_data: ["Supplier lead time"],
    suggested_follow_ups: ["What should I restock?"],
  }

  it("delivers stages (even split across chunks) and resolves with the validated answer", async () => {
    const stages: unknown[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse([
          'event: stage\ndata: {"stage": "plan',
          'ning", "tools": ["Inventory risks"]}\n\n',
          `event: answer\ndata: ${JSON.stringify(answer)}\n\n`,
        ])
      )
    )

    const result = await askCopilotStream({ question: "What should I restock?", language: "banglish" }, (stage) => stages.push(stage))

    expect(stages).toEqual([{ stage: "planning", tools: ["Inventory risks"] }])
    expect(result.answer).toBe("Answer")
    expect(result.missing_data).toEqual([{ message: "Supplier lead time" }])
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(String(url)).toMatch(/\/copilot\/ask\/stream$/)
    expect(JSON.parse(String((init as RequestInit).body))).toMatchObject({ question: "What should I restock?", language: "banglish" })
    vi.unstubAllGlobals()
  })

  it("turns error events and HTTP errors into classifiable errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse(['event: error\ndata: {"error_code": "copilot_failed", "detail": "nope"}\n\n'])))
    await expect(askCopilotStream({ question: "q" }, () => undefined)).rejects.toMatchObject({ response: { status: 500 } })

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { error_code: "rate_limited" } }), { status: 429, headers: { "retry-after": "12" } })))
    await expect(askCopilotStream({ question: "q" }, () => undefined)).rejects.toMatchObject({ response: { status: 429 } })

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse(['event: stage\ndata: {"stage": "writing"}\n\n'])))
    await expect(askCopilotStream({ question: "q" }, () => undefined)).rejects.toMatchObject({ response: { status: 502 } })
    vi.unstubAllGlobals()
  })
})
