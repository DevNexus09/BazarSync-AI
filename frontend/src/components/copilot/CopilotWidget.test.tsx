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

vi.mock("@/hooks/use-products", () => ({
  useProducts: () => ({
    data: [
      {
        id: "product-1",
        title: "Product A",
      },
    ],
  }),
}))

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

async function expandFilters() {
  await userEvent.click(screen.getByRole("button", { name: /^filters/i }))
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

  it("collapses filters by default and keeps chat message area visible", async () => {
    renderWidget()
    await openWidget()

    const filtersButton = screen.getByRole("button", { name: /^filters/i })
    expect(filtersButton).toHaveAttribute("aria-expanded", "false")
    expect(filtersButton).toHaveAttribute("aria-controls", "copilot-filter-content")
    expect(screen.queryByLabelText(/^date range$/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/product filter/i)).not.toBeInTheDocument()
    expect(screen.getByTestId("copilot-message-area")).toBeVisible()
  })

  it("active-filter summary renders while collapsed", async () => {
    renderWidget()
    await openWidget()

    expect(screen.getByText(/last 7 days · all domains · use both · all products/i)).toBeInTheDocument()
  })

  it("clicking filters expands existing controls", async () => {
    renderWidget()
    await openWidget()
    await expandFilters()

    expect(screen.getByLabelText(/date range/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
    expect(screen.getByRole("button", { name: "Revenue" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Competitors" })).toBeInTheDocument()
    expect(
      screen.getByLabelText(/use current database data/i)
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/use business memory/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/use both/i)).toBeChecked()
    expect(screen.getByLabelText(/product filter/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /^filters/i })).toHaveAttribute(
      "aria-expanded",
      "true"
    )
  })

  it("selected filter values persist after collapse", async () => {
    renderWidget()
    await openWidget()
    await expandFilters()

    await userEvent.selectOptions(screen.getByLabelText(/date range/i), "last_30_days")
    await userEvent.click(screen.getByRole("button", { name: "Pricing" }))
    await userEvent.click(screen.getByLabelText(/use business memory/i))
    await userEvent.selectOptions(screen.getByLabelText(/product filter/i), "product-1")
    await expandFilters()

    expect(screen.getByRole("button", { name: /^filters/i })).toHaveAttribute(
      "aria-expanded",
      "false"
    )
    expect(screen.getByText(/last 30 days · pricing · use business memory · product a/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^date range$/i)).not.toBeInTheDocument()

    await expandFilters()

    expect(screen.getByLabelText(/date range/i)).toHaveValue("last_30_days")
    expect(screen.getByRole("button", { name: "Pricing" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
    expect(screen.getByLabelText(/use business memory/i)).toBeChecked()
    expect(screen.getByLabelText(/product filter/i)).toHaveValue("product-1")
  })

  it("includes selected date range, domains, and source flags in ask requests", async () => {
    renderWidget()
    await openWidget()
    await expandFilters()

    await userEvent.selectOptions(screen.getByLabelText(/date range/i), "last_30_days")
    await userEvent.click(screen.getByRole("button", { name: "Revenue" }))
    await userEvent.click(screen.getByRole("button", { name: "Competitors" }))
    await userEvent.click(screen.getByLabelText(/use current database data/i))
    await userEvent.type(
      screen.getByLabelText(/ask copilot a business question/i),
      "What is my revenue this week?"
    )
    await userEvent.click(screen.getByRole("button", { name: /send question/i }))

    await waitFor(() =>
      expect(copilotService.askCopilot).toHaveBeenCalledWith(
        expect.objectContaining({
          question: "What is my revenue this week?",
          domain_filters: ["SALES_REVENUE", "COMPETITOR"],
          include_memory: false,
          include_current_data: true,
          from_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
          to_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
          top_k: 8,
        })
      )
    )
  })

  it("maps source radio selection to current-data and memory booleans", async () => {
    renderWidget()
    await openWidget()
    await expandFilters()

    await userEvent.click(screen.getByLabelText(/use business memory/i))
    await userEvent.type(
      screen.getByLabelText(/ask copilot a business question/i),
      "What happened before?"
    )
    await userEvent.click(screen.getByRole("button", { name: /send question/i }))

    await waitFor(() =>
      expect(copilotService.askCopilot).toHaveBeenLastCalledWith(
        expect.objectContaining({
          include_current_data: false,
          include_memory: true,
        })
      )
    )
    expect(copilotService.askCopilot).toHaveBeenLastCalledWith(
      expect.not.objectContaining({
        memory_source_types: expect.arrayContaining(["database", "memory"]),
        source_types: expect.anything(),
      })
    )

    cleanup()
    window.localStorage.clear()
    vi.mocked(copilotService.askCopilot).mockClear()
    renderWidget()
    await openWidget()
    await userEvent.type(
      screen.getByLabelText(/ask copilot a business question/i),
      "Why is revenue down?"
    )
    await userEvent.click(screen.getByRole("button", { name: /send question/i }))

    await waitFor(() =>
      expect(copilotService.askCopilot).toHaveBeenLastCalledWith(
        expect.objectContaining({
          include_current_data: true,
          include_memory: true,
        })
      )
    )
    expect(copilotService.askCopilot).toHaveBeenLastCalledWith(
      expect.not.objectContaining({
        source_types: expect.anything(),
      })
    )
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
          include_memory: true,
          include_current_data: true,
        })
      )
    )
    expect(copilotService.askCopilot).toHaveBeenCalledWith(
      expect.not.objectContaining({
        source_types: expect.anything(),
      })
    )
  })

  it("calls POST ask service, shows loading, answer, confidence, tools, evidence, and missing data", async () => {
    vi.mocked(copilotService.askCopilot).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          window.setTimeout(() => resolve(askResponse), 50)
        })
    )
    renderWidget()

    await submitQuestion()

    expect(
      screen.getByText(/copilot is checking your business data/i)
    ).toBeInTheDocument()

    await screen.findByText(/restock product a today/i)
    expect(copilotService.askCopilot).toHaveBeenCalledTimes(1)
    expect(screen.getByText(/confidence: high/i)).toBeInTheDocument()
    expect(screen.getByText(/restock recommendations/i)).toBeInTheDocument()
    expect(screen.getByText(/evidence \(1\)/i)).toBeInTheDocument()
    expect(screen.getByText(/supplier lead time is missing/i)).toBeInTheDocument()
  })

  it("clicking a suggested question sends it directly", async () => {
    renderWidget()
    await openWidget()

    await userEvent.click(
      screen.getByRole("button", { name: /which competitor is hurting me/i })
    )

    await waitFor(() =>
      expect(copilotService.askCopilot).toHaveBeenCalledWith(
        expect.objectContaining({
          question: "Which competitor is hurting me?",
        })
      )
    )
  })

  it("renders grouped suggestions and submits broad business questions", async () => {
    renderWidget()
    await openWidget()

    expect(screen.getByText("Business overview")).toBeInTheDocument()
    expect(screen.getAllByText("Revenue").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Competitors").length).toBeGreaterThan(0)

    await userEvent.click(
      screen.getByRole("button", { name: /how many products do i have listed/i })
    )
    await waitFor(() =>
      expect(copilotService.askCopilot).toHaveBeenLastCalledWith(
        expect.objectContaining({
          question: "How many products do I have listed?",
        })
      )
    )

    await screen.findByText(/restock product a today/i)

    cleanup()
    window.localStorage.clear()
    vi.mocked(copilotService.askCopilot).mockClear()
    renderWidget()
    await openWidget()
    await userEvent.click(
      screen.getByRole("button", { name: /what is my revenue this week/i })
    )
    await waitFor(() =>
      expect(copilotService.askCopilot).toHaveBeenLastCalledWith(
        expect.objectContaining({
          question: "What is my revenue this week?",
        })
      )
    )

    cleanup()
    window.localStorage.clear()
    vi.mocked(copilotService.askCopilot).mockClear()
    renderWidget()
    await openWidget()
    await userEvent.click(
      screen.getByRole("button", { name: /which competitor is hurting me/i })
    )
    await waitFor(() =>
      expect(copilotService.askCopilot).toHaveBeenLastCalledWith(
        expect.objectContaining({
          question: "Which competitor is hurting me?",
        })
      )
    )
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
    expect(screen.getByText(/confidence: high/i)).toBeInTheDocument()
    expect(screen.getByText(/revenue summary/i)).toBeInTheDocument()
    expect(screen.getByText(/evidence \(1\)/i)).toBeInTheDocument()
    expect(screen.getByText(/sales completeness is partial/i)).toBeInTheDocument()
    expect(screen.getAllByText(/sales_records/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/review sales import coverage/i)).toBeInTheDocument()
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
    expect(screen.getByText(/confidence: no context/i)).toBeInTheDocument()
    expect(
      screen.getByText(/not enough seller-specific business data was found/i)
    ).toBeInTheDocument()
    expect(screen.getByText(/add product setup data/i)).toBeInTheDocument()
    expect(screen.getByText(/import sales records/i)).toBeInTheDocument()
    expect(screen.getByText(/run memory indexing/i)).toBeInTheDocument()
  })

  it("renders memory coverage warnings from backend", async () => {
    vi.mocked(copilotService.askCopilot).mockResolvedValueOnce({
      ...askResponse,
      message_id: "message-memory-warning",
      memory_coverage_warning: true,
    })
    renderWidget()

    await submitQuestion("What happened last time sales dropped?")

    expect(
      await screen.findByText(/some business history is not indexed yet/i)
    ).toBeInTheDocument()
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

  it("uses mobile contained and desktop compact panel classes", async () => {
    renderWidget()
    await openWidget()

    const panel = screen.getByTestId("copilot-chat-panel")
    expect(panel).toHaveClass("h-[86dvh]")
    expect(panel).toHaveClass("w-screen")
    expect(panel).toHaveClass("sm:h-[620px]")
    expect(panel).toHaveClass("sm:w-[420px]")
    expect(panel).toHaveClass("sm:max-h-[calc(100dvh-3rem)]")
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
