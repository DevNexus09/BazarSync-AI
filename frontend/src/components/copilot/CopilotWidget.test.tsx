import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi, beforeEach } from "vitest"
import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"

import { CopilotWidget } from "@/components/copilot/CopilotWidget"
import { shouldShowCopilotWidget } from "@/components/copilot/copilot-visibility"
import * as copilotService from "@/services/copilot-service"
import type { CopilotAskResponse } from "@/types/copilot"

vi.mock("@/services/copilot-service", () => ({
  listCopilotConversations: vi.fn(),
  createCopilotConversation: vi.fn(),
  getCopilotConversation: vi.fn(),
  askCopilot: vi.fn(),
  listCopilotTools: vi.fn(),
  listActionProposals: vi.fn(),
  approveActionProposal: vi.fn(),
  rejectActionProposal: vi.fn(),
  askCopilotStream: vi.fn(),
  submitCopilotFeedback: vi.fn(),
  getCopilotFeatures: vi.fn(),
}))

const askResponse: CopilotAskResponse = {
  conversation_id: "conversation-1",
  message_id: "message-1",
  answer: "Restock Product A today based on current inventory risk.",
  summary: "Restock Product A.",
  confidence: "HIGH",
  language: "en",
  intent: "RESTOCK_ADVICE",
  tools_used: [{ name: "get_restock_recommendations", status: "SUCCEEDED" }],
  evidence: [
    {
      evidence_id: "ev-1",
      source_type: "inventory",
      title: "Product A reorder recommendation",
      event_time: null,
    },
  ],
  missing_data: [{ message: "Supplier lead time is missing." }],
  recommended_next_steps: ["Review supplier lead time."],
  action_proposal: null,
}

const actionResponse: CopilotAskResponse = {
  ...askResponse,
  message_id: "message-2",
  answer: "I saved a price-change proposal for review.",
  confidence: "MEDIUM",
  intent: "ACTION_REQUEST_PRICE_CHANGE",
  action_proposal: {
    id: "proposal-1",
    action_type: "PRICE_CHANGE",
    status: "PROPOSED",
    summary: "Lower price by 5% after MarginGuard review.",
    requires_confirmation: true,
    safety_checks: { marketplace_mutation_performed: false },
    expected_impact: { direction: "unknown" },
  },
}

const conversationNotFoundError = Object.assign(
  new Error("Request failed with status code 404"),
  {
    response: {
      status: 404,
      data: {
        detail: {
          error_code: "conversation_not_found",
          detail: "Conversation not found.",
        },
      },
    },
  }
)

function renderWidget(path = "/app/dashboard") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <CopilotWidget />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

async function openWidget() {
  await userEvent.click(
    screen.getByRole("button", { name: /open ai business copilot/i })
  )
}

async function submitQuestion(question = "What should I restock today?") {
  await openWidget()
  await userEvent.type(
    screen.getByLabelText(/ask copilot a business question/i),
    question
  )
  await userEvent.click(screen.getByRole("button", { name: /send question/i }))
}

describe("shouldShowCopilotWidget", () => {
  it("renders on dashboard pages and hides on landing, auth, and settings pages", () => {
    expect(shouldShowCopilotWidget("/app/dashboard")).toBe(true)
    expect(shouldShowCopilotWidget("/app/products/product-1")).toBe(true)
    expect(shouldShowCopilotWidget("/")).toBe(false)
    expect(shouldShowCopilotWidget("/login")).toBe(false)
    expect(shouldShowCopilotWidget("/register")).toBe(false)
    expect(shouldShowCopilotWidget("/signup")).toBe(false)
    expect(shouldShowCopilotWidget("/forgot-password")).toBe(false)
    expect(shouldShowCopilotWidget("/auth/callback")).toBe(false)
    expect(shouldShowCopilotWidget("/app/settings")).toBe(false)
    expect(shouldShowCopilotWidget("/app/account/profile")).toBe(false)
    expect(shouldShowCopilotWidget("/app/billing")).toBe(false)
  })
})

describe("CopilotWidget", () => {
  beforeEach(() => {
    if (!window.localStorage) {
      const store = new Map<string, string>()
      Object.defineProperty(window, "localStorage", {
        value: {
          clear: () => store.clear(),
          getItem: (key: string) => store.get(key) ?? null,
          removeItem: (key: string) => store.delete(key),
          setItem: (key: string, value: string) => store.set(key, value),
        },
        configurable: true,
      })
    }
    window.localStorage.clear()
    vi.mocked(copilotService.askCopilot).mockReset()
    vi.mocked(copilotService.listCopilotConversations).mockReset()
    vi.mocked(copilotService.getCopilotConversation).mockReset()
    vi.mocked(copilotService.approveActionProposal).mockReset()
    vi.mocked(copilotService.rejectActionProposal).mockReset()
    vi.mocked(copilotService.listCopilotConversations).mockResolvedValue({
      items: [],
      total: 0,
      limit: 20,
      offset: 0,
    })
    vi.mocked(copilotService.askCopilot).mockResolvedValue(askResponse)
    vi.mocked(copilotService.askCopilotStream).mockReset()
    vi.mocked(copilotService.submitCopilotFeedback).mockReset()
    vi.mocked(copilotService.submitCopilotFeedback).mockResolvedValue({ message_id: "message-1", rating: "up" })
    vi.mocked(copilotService.getCopilotFeatures).mockReset()
    vi.mocked(copilotService.getCopilotFeatures).mockResolvedValue({
      multilingual: false,
      languages: ["auto", "en", "bn"],
      streaming: false,
      follow_ups: false,
      feedback: true,
      conversation_memory: false,
    })
    vi.mocked(copilotService.approveActionProposal).mockResolvedValue({
      proposal: {
        ...actionResponse.action_proposal!,
        status: "APPROVED",
      },
      message:
        "Execution is not implemented yet. This proposal has been approved for future execution.",
      executed: false,
    })
    vi.mocked(copilotService.rejectActionProposal).mockResolvedValue({
      proposal: {
        ...actionResponse.action_proposal!,
        status: "REJECTED",
      },
      message: "This proposal has been rejected. No marketplace action was executed.",
      executed: false,
    })
  })

  it("renders the floating button on dashboard pages", () => {
    renderWidget()

    expect(
      screen.getByRole("button", { name: /open ai business copilot/i })
    ).toBeInTheDocument()
  })

  it("does not render the floating button on landing, auth, or settings pages", () => {
    const { rerender } = renderWidget("/")
    expect(
      screen.queryByRole("button", { name: /open ai business copilot/i })
    ).not.toBeInTheDocument()

    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/login"]}>
          <CopilotWidget />
        </MemoryRouter>
      </QueryClientProvider>
    )
    expect(
      screen.queryByRole("button", { name: /open ai business copilot/i })
    ).not.toBeInTheDocument()

    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/app/settings"]}>
          <CopilotWidget />
        </MemoryRouter>
      </QueryClientProvider>
    )
    expect(
      screen.queryByRole("button", { name: /open ai business copilot/i })
    ).not.toBeInTheDocument()
  })

  it("opens and closes the chat panel with accessible labels", async () => {
    renderWidget()
    await openWidget()

    expect(
      screen.getByRole("dialog", { name: /ai business copilot/i })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /close ai business copilot/i })
    ).toBeInTheDocument()

    await userEvent.click(
      screen.getByRole("button", { name: /close ai business copilot/i })
    )

    expect(screen.getByTestId("copilot-chat-panel")).toHaveClass(
      "pointer-events-none"
    )
  })

  it("shows no filter controls and keeps the chat message area visible", async () => {
    renderWidget()
    await openWidget()

    expect(screen.queryByRole("button", { name: /^filters/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/date range/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/product filter/i)).not.toBeInTheDocument()
    expect(screen.getByTestId("copilot-message-area")).toBeVisible()
  })

  it("sends no filters: only the question, conversation and language", async () => {
    renderWidget()
    await openWidget()
    await userEvent.type(
      screen.getByLabelText(/ask copilot a business question/i),
      "What was my revenue from 2026-10-01 to 2026-10-31?"
    )
    await userEvent.click(screen.getByRole("button", { name: /send question/i }))

    await waitFor(() => expect(copilotService.askCopilot).toHaveBeenCalled())
    const request = vi.mocked(copilotService.askCopilot).mock.calls[0][0]
    expect(request.question).toBe("What was my revenue from 2026-10-01 to 2026-10-31?")
    expect(Object.keys(request).sort()).toEqual(["conversation_id", "language", "question"])
  })

  it("submits with Enter and uses Shift+Enter for a new line", async () => {
    renderWidget()
    await openWidget()

    const input = screen.getByLabelText(/ask copilot a business question/i)
    await userEvent.type(input, "Line one")
    await userEvent.keyboard("{Shift>}{Enter}{/Shift}")
    await userEvent.type(input, "Line two")
    expect(input).toHaveValue("Line one\nLine two")

    await userEvent.keyboard("{Enter}")

    await waitFor(() =>
      expect(copilotService.askCopilot).toHaveBeenCalledWith(
        expect.objectContaining({
          question: "Line one\nLine two",
        })
      )
    )
    expect(copilotService.askCopilot).toHaveBeenCalledWith(
      expect.not.objectContaining({
        source_types: expect.anything(),
      })
    )
  })

  it("calls POST ask service, shows loading and only the answer", async () => {
    vi.mocked(copilotService.askCopilot).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          window.setTimeout(() => resolve(askResponse), 50)
        })
    )
    renderWidget()

    await submitQuestion()

    expect(
      screen.getByRole("status")
    ).toBeInTheDocument()

    await screen.findByText(/restock product a today/i)
    expect(copilotService.askCopilot).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/confidence: high/i)).toBeNull()
    expect(screen.queryByText(/evidence \(1\)/i)).toBeNull()
    expect(screen.getByText(/supplier lead time is missing/i)).not.toBeVisible()
  })

  it("shows no suggested question cards in an empty chat", async () => {
    renderWidget()
    await openWidget()

    expect(screen.getByText("Ask your AI Business Copilot")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /which competitor is hurting me/i })).toBeNull()
    expect(screen.queryByText("Business overview")).toBeNull()
  })

  it("hydrates prior conversation messages when opened", async () => {
    vi.mocked(copilotService.listCopilotConversations).mockResolvedValue({
      items: [
        {
          id: "conversation-2",
          seller_id: "seller-1",
          title: "Revenue",
          status: "ACTIVE",
          language: "en",
          created_at: "2026-07-01T00:00:00Z",
          updated_at: "2026-07-02T00:00:00Z",
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    })
    vi.mocked(copilotService.getCopilotConversation).mockResolvedValue({
      conversation: {
        id: "conversation-2",
        seller_id: "seller-1",
        title: "Revenue",
        status: "ACTIVE",
        language: "en",
        created_at: "2026-07-01T00:00:00Z",
        updated_at: "2026-07-02T00:00:00Z",
      },
      messages: [
        {
          id: "user-message-1",
          seller_id: "seller-1",
          conversation_id: "conversation-2",
          role: "USER",
          content: "What is my revenue this week?",
          language: "en",
          created_at: "2026-07-02T00:00:00Z",
        },
        {
          id: "assistant-message-1",
          seller_id: "seller-1",
          conversation_id: "conversation-2",
          role: "ASSISTANT",
          content: "Revenue is up this week.",
          language: "en",
          answer_confidence: "HIGH",
          summary: "Revenue summary.",
          question_type: "REVENUE",
          domains_used: ["sales"],
          tools_used: [
            {
              name: "get_revenue_summary",
              status: "SUCCEEDED",
              evidence_count: 1,
              missing_data_count: 1,
            },
          ],
          evidence: [
            {
              evidence_id: "sales:1",
              source_type: "tool",
              source_table: "sales_records",
              title: "Sales evidence",
            },
          ],
          missing_data: [{ message: "Sales completeness is partial." }],
          data_freshness: [
            {
              domain: "sales",
              source_table: "sales_records",
              status: "FRESH",
              message: "Latest sale imported today.",
            },
          ],
          recommended_next_steps: ["Review sales import coverage."],
          action_proposal: {
            id: "proposal-2",
            action_type: "PROMOTION_PLAN",
            status: "PROPOSED",
            requires_confirmation: true,
          },
          created_at: "2026-07-02T00:00:01Z",
        },
      ],
    })

    renderWidget()
    await openWidget()

    expect(await screen.findByText("Revenue is up this week.")).toBeInTheDocument()
    expect(screen.getByText("What is my revenue this week?")).toBeInTheDocument()
    expect(screen.queryByText(/confidence: high/i)).toBeNull()
    expect(screen.queryByText(/evidence \(1\)/i)).toBeNull()
    expect(screen.getByText(/sales completeness is partial/i)).not.toBeVisible()
    expect(screen.getByText(/action proposal: promotion_plan/i)).toBeInTheDocument()
    expect(window.localStorage.getItem("bazarsync:copilot:conversation-id")).toBe(
      "conversation-2"
    )
  })

  it("clears a stale stored conversation id when hydration returns not found", async () => {
    window.localStorage.setItem(
      "bazarsync:copilot:conversation-id",
      "stale-conversation"
    )
    vi.mocked(copilotService.getCopilotConversation).mockRejectedValueOnce(
      conversationNotFoundError
    )

    renderWidget()
    await openWidget()

    await waitFor(() =>
      expect(copilotService.getCopilotConversation).toHaveBeenCalledWith(
        "stale-conversation"
      )
    )
    await waitFor(() =>
      expect(
        window.localStorage.getItem("bazarsync:copilot:conversation-id")
      ).toBeNull()
    )

    await userEvent.type(
      screen.getByLabelText(/ask copilot a business question/i),
      "What should I restock?"
    )
    await userEvent.click(screen.getByRole("button", { name: /send question/i }))

    await waitFor(() =>
      expect(copilotService.askCopilot).toHaveBeenCalledWith(
        expect.objectContaining({
          conversation_id: undefined,
          question: "What should I restock?",
        })
      )
    )
  })

  it("reloads stored conversation id and continues hydrated conversation with follow-up", async () => {
    window.localStorage.setItem(
      "bazarsync:copilot:conversation-id",
      "conversation-2"
    )
    vi.mocked(copilotService.getCopilotConversation).mockResolvedValueOnce({
      conversation: {
        id: "conversation-2",
        conversation_id: "conversation-2",
        seller_id: "seller-1",
        user_id: "seller-1",
        title: "Revenue",
        status: "ACTIVE",
        language: "en",
        created_at: "2026-07-02T00:00:00Z",
        updated_at: "2026-07-02T00:00:01Z",
      },
      messages: [
        {
          id: "message-user-1",
          seller_id: "seller-1",
          conversation_id: "conversation-2",
          role: "USER",
          content: "Which product generated the most revenue this month?",
          language: "en",
          created_at: "2026-07-02T00:00:00Z",
        },
        {
          id: "message-assistant-1",
          seller_id: "seller-1",
          conversation_id: "conversation-2",
          role: "ASSISTANT",
          content: "Product A generated the most revenue.",
          language: "en",
          answer_confidence: "HIGH",
          response_metadata_json: {
            summary: "Top revenue product.",
            question_type: "ANALYTIC",
          },
          domains_used_json: ["SALES_REVENUE"],
          tools_used_json: [{ name: "get_top_products_by_revenue", status: "SUCCEEDED" }],
          evidence_json: [],
          missing_data_json: [],
          data_freshness_json: [],
          recommended_next_steps_json: [],
          created_at: "2026-07-02T00:00:01Z",
        },
      ],
    })

    renderWidget()
    await openWidget()

    expect(copilotService.getCopilotConversation).toHaveBeenCalledWith(
      "conversation-2"
    )
    expect(
      await screen.findByText(/which product generated the most revenue/i)
    ).toBeInTheDocument()

    await userEvent.type(
      screen.getByLabelText(/ask copilot a business question/i),
      "What about last month?"
    )
    await userEvent.click(screen.getByRole("button", { name: /send question/i }))

    await waitFor(() =>
      expect(copilotService.askCopilot).toHaveBeenCalledWith(
        expect.objectContaining({
          conversation_id: "conversation-2",
          question: "What about last month?",
        })
      )
    )
  })

  it("retries ask without a stale conversation id when backend rejects it", async () => {
    window.localStorage.setItem(
      "bazarsync:copilot:conversation-id",
      "stale-conversation"
    )
    vi.mocked(copilotService.getCopilotConversation).mockImplementation(
      () => new Promise(() => {})
    )
    vi.mocked(copilotService.askCopilot)
      .mockRejectedValueOnce(conversationNotFoundError)
      .mockResolvedValueOnce(askResponse)

    renderWidget()
    await openWidget()

    await waitFor(() =>
      expect(copilotService.getCopilotConversation).toHaveBeenCalledWith(
        "stale-conversation"
      )
    )
    await userEvent.type(
      screen.getByLabelText(/ask copilot a business question/i),
      "What should I restock?"
    )
    await userEvent.click(screen.getByRole("button", { name: /send question/i }))

    await waitFor(() => expect(copilotService.askCopilot).toHaveBeenCalledTimes(2))
    expect(copilotService.askCopilot).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        conversation_id: "stale-conversation",
        question: "What should I restock?",
      })
    )
    expect(copilotService.askCopilot).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        conversation_id: undefined,
        question: "What should I restock?",
      })
    )
    expect(await screen.findByText(/restock product a today/i)).toBeInTheDocument()
    expect(window.localStorage.getItem("bazarsync:copilot:conversation-id")).toBe(
      "conversation-1"
    )
  })

  it("renders API error and no-context states", async () => {
    vi.mocked(copilotService.askCopilot).mockRejectedValueOnce(new Error("boom"))
    renderWidget()

    await submitQuestion("Why is revenue down this week?")

    await screen.findByRole("alert")
    expect(screen.getByText(/please try again/i)).toBeInTheDocument()

    vi.mocked(copilotService.askCopilot).mockResolvedValueOnce({
      ...askResponse,
      message_id: "message-no-context",
      answer:
        "I could not find enough seller-specific business history to answer this reliably.",
      confidence: "NO_CONTEXT",
      evidence: [],
      missing_data: [{ message: "No seller-specific history found." }],
    })

    await userEvent.type(
      screen.getByLabelText(/ask copilot a business question/i),
      "What should I restock?"
    )
    await userEvent.click(screen.getByRole("button", { name: /send question/i }))

    await screen.findByText(/not find enough seller-specific/i)
    expect(screen.queryByText(/confidence: no context/i)).toBeNull()
    expect(screen.queryByText(/run memory indexing/i)).toBeNull()
  })

  it("does not show memory coverage warnings in the answer", async () => {
    vi.mocked(copilotService.askCopilot).mockResolvedValueOnce({
      ...askResponse,
      message_id: "message-memory-warning",
      memory_coverage_warning: true,
    })
    renderWidget()

    await submitQuestion("What happened last time sales dropped?")

    await screen.findByText(/restock product a today/i)
    expect(screen.queryByText(/some business history is not indexed yet/i)).toBeNull()
  })

  it("renders action proposal card and approve/reject call the API without execution claims", async () => {
    vi.mocked(copilotService.askCopilot).mockResolvedValue(actionResponse)
    renderWidget()

    await submitQuestion("Lower price by 5%")

    await screen.findByText(/action proposal: price_change/i)
    expect(
      screen.getByText(/approval does not execute live marketplace changes yet/i)
    ).toBeInTheDocument()

    await userEvent.click(screen.getByRole("button", { name: /approve/i }))
    await waitFor(() =>
      expect(copilotService.approveActionProposal).toHaveBeenCalled()
    )
    expect(vi.mocked(copilotService.approveActionProposal).mock.calls[0][0]).toBe(
      "proposal-1"
    )
    expect(await screen.findByText(/execution is not implemented yet/i)).toBeInTheDocument()

    cleanup()
    vi.mocked(copilotService.askCopilot).mockResolvedValue({
      ...actionResponse,
      message_id: "message-3",
    })
    renderWidget()
    await submitQuestion("Lower price by 5%")
    await screen.findByText(/action proposal: price_change/i)
    await userEvent.click(screen.getByRole("button", { name: /reject/i }))
    await waitFor(() =>
      expect(copilotService.rejectActionProposal).toHaveBeenCalled()
    )
    expect(vi.mocked(copilotService.rejectActionProposal).mock.calls[0][0]).toBe(
      "proposal-1"
    )
  })

  it("is a full-screen sheet on phones, a side panel on desktop, and can go full page", async () => {
    renderWidget()
    await openWidget()

    const panel = screen.getByTestId("copilot-chat-panel")
    expect(panel).toHaveClass("inset-0", "h-[100dvh]", "w-screen", "sm:h-[640px]", "sm:w-[440px]", "sm:max-h-[calc(100dvh-3rem)]")

    await userEvent.click(screen.getByRole("button", { name: /full page/i }))

    expect(panel).toHaveAttribute("data-expanded")
    expect(panel).toHaveClass("sm:inset-4")
    expect(panel).not.toHaveClass("sm:w-[440px]")
  })

  it("does not create a dedicated copilot page route", () => {
    const routesSource = readFileSync("src/routes/index.tsx", "utf8")
    expect(routesSource).not.toMatch(/path:\s*["']copilot["']/)
    expect(routesSource).not.toContain(["/dashboard", "copilot"].join("/"))
  })
})

describe("frontend secret exposure", () => {
  it("does not include a Groq frontend key", () => {
    const files = collectSourceFiles("src")
    const combined = files.map((file) => readFileSync(file, "utf8")).join("\n")
    const forbiddenKeyName = ["VITE", "GROQ", "API", "KEY"].join("_")
    expect(combined).not.toContain(forbiddenKeyName)
  })

  it("does not expose raw assistant internals in frontend source", () => {
    const files = collectSourceFiles("src")
    const combined = files.map((file) => readFileSync(file, "utf8")).join("\n")
    expect(combined).not.toContain(["system", "_", "prompt"].join(""))
    expect(combined).not.toContain(["developer", "_", "prompt"].join(""))
    expect(combined).not.toContain(["raw", "_", "prompt"].join(""))
    expect(combined).not.toContain(["raw", "_", "embedding"].join(""))
    expect(combined).not.toContain(["embedding", "_", "vector"].join(""))
  })
})

function collectSourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry)
    const stat = statSync(path)
    if (stat.isDirectory()) {
      return collectSourceFiles(path)
    }
    return /\.(ts|tsx|js|jsx)$/.test(path) ? [path] : []
  })
}
