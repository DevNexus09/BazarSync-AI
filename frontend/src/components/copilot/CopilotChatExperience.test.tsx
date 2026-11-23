import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { CopilotWidget } from "@/components/copilot/CopilotWidget"
import * as copilotService from "@/services/copilot-service"
import type { CopilotAskResponse, CopilotFeatures } from "@/types/copilot"

vi.mock("@/services/copilot-service", () => ({
  listCopilotConversations: vi.fn(),
  createCopilotConversation: vi.fn(),
  getCopilotConversation: vi.fn(),
  askCopilot: vi.fn(),
  askCopilotStream: vi.fn(),
  listCopilotTools: vi.fn(),
  listActionProposals: vi.fn(),
  approveActionProposal: vi.fn(),
  rejectActionProposal: vi.fn(),
  submitCopilotFeedback: vi.fn(),
  getCopilotFeatures: vi.fn(),
}))

const answer: CopilotAskResponse = {
  conversation_id: "conversation-1",
  message_id: "message-1",
  answer: "**Quick recommendation**\n- Restock Product A",
  summary: "Restock Product A.",
  confidence: "HIGH",
  language: "en",
  tools_used: [{ name: "get_restock_recommendations", status: "SUCCEEDED" }],
  evidence: [],
  missing_data: [],
  recommended_next_steps: [],
  action_proposal: null,
  suggested_follow_ups: ["Which products are closest to stocking out?"],
}

const baseFeatures: CopilotFeatures = {
  multilingual: true,
  languages: ["auto", "en", "bn", "banglish"],
  streaming: false,
  follow_ups: true,
  feedback: true,
  conversation_memory: false,
}

function renderWidget() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/app/dashboard"]}>
        <CopilotWidget />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

async function open() {
  await userEvent.click(screen.getByRole("button", { name: /open ai business copilot/i }))
}

async function ask(question: string) {
  await userEvent.type(screen.getByLabelText(/ask copilot a business question/i), question)
  await userEvent.click(screen.getByRole("button", { name: /send question/i }))
}

function lastRequest() {
  const calls = vi.mocked(copilotService.askCopilot).mock.calls
  return calls[calls.length - 1][0]
}

describe("Copilot chat experience", () => {
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
    vi.mocked(copilotService.askCopilot).mockReset().mockResolvedValue(answer)
    vi.mocked(copilotService.askCopilotStream).mockReset()
    vi.mocked(copilotService.submitCopilotFeedback).mockReset().mockResolvedValue({ message_id: "message-1", rating: "up" })
    vi.mocked(copilotService.getCopilotFeatures).mockReset().mockResolvedValue(baseFeatures)
    vi.mocked(copilotService.getCopilotConversation).mockReset()
    vi.mocked(copilotService.listCopilotConversations).mockReset().mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
  })

  it("sends the chosen reply language and remembers it", async () => {
    renderWidget()
    await open()
    const select = await screen.findByLabelText("Reply language")
    await screen.findByRole("option", { name: "Banglish" })

    await userEvent.selectOptions(select, "banglish")
    await ask("amar sales koto?")

    await waitFor(() => expect(copilotService.askCopilot).toHaveBeenCalled())
    expect(lastRequest().language).toBe("banglish")
    expect(window.localStorage.getItem("bazarsync:copilot:language")).toBe("banglish")
    // Interface strings follow the chosen language.
    expect(screen.getByText("Shudhu apnar business data theke uttor")).toBeInTheDocument()
  })

  it("hides Banglish when the backend does not support it", async () => {
    vi.mocked(copilotService.getCopilotFeatures).mockResolvedValue({ ...baseFeatures, multilingual: false, languages: ["auto", "en", "bn"] })
    renderWidget()
    await open()

    await screen.findByRole("option", { name: "বাংলা" })
    expect(screen.queryByRole("option", { name: "Banglish" })).toBeNull()
  })

  it("renders markdown answers without tool badges and follow-up chips that ask again", async () => {
    renderWidget()
    await open()
    await ask("What should I restock?")

    expect((await screen.findByText("Quick recommendation")).tagName).toBe("STRONG")
    // Tool names live only in the collapsed Sources section, never in the answer itself.
    expect(screen.getByText("Restock recommendations")).not.toBeVisible()

    await userEvent.click(screen.getByRole("button", { name: "Which products are closest to stocking out?" }))
    await waitFor(() => expect(copilotService.askCopilot).toHaveBeenCalledTimes(2))
    expect(lastRequest().question).toBe("Which products are closest to stocking out?")
    expect(lastRequest().conversation_id).toBe("conversation-1")
  })

  it("starts a new chat without a conversation id", async () => {
    renderWidget()
    await open()
    await ask("What should I restock?")
    await screen.findByText("Quick recommendation")

    await userEvent.click(screen.getByRole("button", { name: "New chat" }))
    expect(screen.queryByText("Quick recommendation")).toBeNull()

    await ask("Why is revenue down?")
    await waitFor(() => expect(copilotService.askCopilot).toHaveBeenCalledTimes(2))
    expect(lastRequest().conversation_id).toBeUndefined()
  })

  it("lists earlier conversations and opens one", async () => {
    vi.mocked(copilotService.listCopilotConversations).mockResolvedValue({
      items: [
        { id: "c-old", seller_id: "s", title: "Restock questions", status: "ACTIVE", language: "en", created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z" },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    })
    vi.mocked(copilotService.getCopilotConversation).mockResolvedValue({
      conversation: { id: "c-old", seller_id: "s", status: "ACTIVE", language: "en", created_at: "", updated_at: "" },
      messages: [
        { id: "u1", seller_id: "s", conversation_id: "c-old", role: "USER", content: "What should I restock?", language: "en", created_at: "" },
      ],
    })
    renderWidget()
    await open()

    await userEvent.click(screen.getByRole("button", { name: "Conversations" }))
    await userEvent.click(await screen.findByRole("button", { name: "Restock questions" }))

    await waitFor(() => expect(copilotService.getCopilotConversation).toHaveBeenCalledWith("c-old"))
    expect(await screen.findByText("What should I restock?")).toBeInTheDocument()
  })

  it("keeps a failed question, explains rate limits, and retries it", async () => {
    vi.mocked(copilotService.askCopilot).mockRejectedValueOnce(Object.assign(new Error("429"), { response: { status: 429 } }))
    renderWidget()
    await open()
    await ask("Why is revenue down?")

    expect(await screen.findByText(/you are asking very quickly/i)).toBeInTheDocument()
    expect(screen.getByText("Not sent")).toBeInTheDocument()
    expect((screen.getByLabelText(/ask copilot a business question/i) as HTMLTextAreaElement).value).toBe("Why is revenue down?")

    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByText("Quick recommendation")).toBeInTheDocument()
    expect(screen.queryByText("Not sent")).toBeNull()
    expect(lastRequest().question).toBe("Why is revenue down?")
    expect((screen.getByLabelText(/ask copilot a business question/i) as HTMLTextAreaElement).value).toBe("")
  })

  it("explains timeouts and server errors differently", async () => {
    vi.mocked(copilotService.askCopilot)
      .mockRejectedValueOnce(Object.assign(new Error("timeout of 30000ms exceeded"), { code: "ECONNABORTED" }))
      .mockRejectedValueOnce(Object.assign(new Error("500"), { response: { status: 500 } }))
    renderWidget()
    await open()

    await ask("a")
    expect(await screen.findByText(/took too long/i)).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText(/ask copilot a business question/i))
    await ask("b")
    expect(await screen.findByText(/service had a problem/i)).toBeInTheDocument()
  })

  it("sends answer feedback for the assistant message", async () => {
    renderWidget()
    await open()
    await ask("What should I restock?")
    await screen.findByText("Quick recommendation")

    await userEvent.click(screen.getByRole("button", { name: "Helpful" }))

    await waitFor(() => expect(copilotService.submitCopilotFeedback).toHaveBeenCalledWith("message-1", "up"))
    expect(screen.getByRole("button", { name: "Helpful" })).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByText("Thanks for the feedback")).toBeInTheDocument()
  })

  it("asks the same question again from an answer", async () => {
    renderWidget()
    await open()
    await ask("What should I restock?")
    await screen.findByText("Quick recommendation")

    await userEvent.click(screen.getByRole("button", { name: "Ask again" }))

    await waitFor(() => expect(copilotService.askCopilot).toHaveBeenCalledTimes(2))
    expect(lastRequest().question).toBe("What should I restock?")
  })

  it("streams progress stages when the backend supports it", async () => {
    vi.mocked(copilotService.getCopilotFeatures).mockResolvedValue({ ...baseFeatures, streaming: true })
    let release: (value: CopilotAskResponse) => void = () => undefined
    vi.mocked(copilotService.askCopilotStream).mockImplementation((_request, onStage) => {
      onStage({ stage: "tool", tool: "Restock recommendations", status: "SUCCEEDED" })
      return new Promise<CopilotAskResponse>((resolve) => {
        release = resolve
      })
    })
    renderWidget()
    await open()
    await screen.findByRole("option", { name: "Banglish" })
    await ask("What should I restock?")

    expect(await screen.findByText("Checking restock recommendations…")).toBeInTheDocument()
    expect(copilotService.askCopilot).not.toHaveBeenCalled()
    release(answer)
    expect(await screen.findByText("Quick recommendation")).toBeInTheDocument()
  })

  it("closes with Escape from anywhere in the panel", async () => {
    renderWidget()
    await open()
    const newChat = screen.getByRole("button", { name: "New chat" })
    newChat.focus()

    await userEvent.keyboard("{Escape}")

    await waitFor(() => expect(screen.getByTestId("copilot-chat-panel")).toHaveClass("opacity-0"))
  })
})
