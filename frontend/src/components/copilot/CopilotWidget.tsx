import { useCallback, useEffect, useRef, useState } from "react"
import { ChevronDown } from "lucide-react"
import { useLocation } from "react-router-dom"

import { CopilotChatPanel } from "@/components/copilot/CopilotChatPanel"
import { CopilotEmptyState } from "@/components/copilot/CopilotEmptyState"
import { CopilotErrorState } from "@/components/copilot/CopilotErrorState"
import { CopilotFilterControls } from "@/components/copilot/CopilotFilterControls"
import { CopilotFloatingButton } from "@/components/copilot/CopilotFloatingButton"
import { CopilotMessageList } from "@/components/copilot/CopilotMessageList"
import { CopilotProductFilter } from "@/components/copilot/CopilotProductFilter"
import { CopilotQuestionInput } from "@/components/copilot/CopilotQuestionInput"
import {
  copilotSourceModes,
  resolveDateRange,
} from "@/components/copilot/copilot-filter-utils"
import { shouldShowCopilotWidget } from "@/components/copilot/copilot-visibility"
import {
  useAskCopilot,
  useCopilotConversation,
  useCopilotConversations,
} from "@/hooks/useCopilot"
import { useProducts } from "@/hooks/use-products"
import { cn } from "@/lib/utils"
import type {
  CopilotActionProposal,
  CopilotAskRequest,
  CopilotAskResponse,
  CopilotDataFreshness,
  CopilotConversation,
  CopilotEvidence,
  CopilotMessage,
  CopilotLocalMessage,
  CopilotMissingData,
  CopilotToolUsed,
  CopilotSourceMode,
  CopilotDomain,
} from "@/types/copilot"

const conversationStorageKey = "bazarsync:copilot:conversation-id"

const copilotStorage = {
  get() {
    try {
      return window.localStorage?.getItem(conversationStorageKey) ?? null
    } catch {
      return null
    }
  },
  set(value: string) {
    try {
      window.localStorage?.setItem(conversationStorageKey, value)
    } catch {
      // Conversation hydration still works for the active widget session.
    }
  },
  remove() {
    try {
      window.localStorage?.removeItem(conversationStorageKey)
    } catch {
      // A stale in-memory conversation id can still be cleared for this session.
    }
  },
}

const isCopilotConversationNotFoundError = (error: unknown): boolean => {
  if (!error || typeof error !== "object") {
    return false
  }

  const response = (error as { response?: { status?: number; data?: unknown } })
    .response
  const data = response?.data
  if (data && typeof data === "object") {
    const payload = data as {
      detail?: unknown
      error_code?: unknown
      message?: unknown
    }
    if (payload.error_code === "conversation_not_found") {
      return true
    }
    if (payload.detail && typeof payload.detail === "object") {
      const detail = payload.detail as { error_code?: unknown; detail?: unknown }
      if (detail.error_code === "conversation_not_found") {
        return true
      }
      if (
        typeof detail.detail === "string" &&
        /conversation not found/i.test(detail.detail)
      ) {
        return response?.status === 404
      }
    }
    if (
      typeof payload.detail === "string" &&
      /conversation not found/i.test(payload.detail)
    ) {
      return response?.status === 404
    }
    if (
      typeof payload.message === "string" &&
      /conversation not found/i.test(payload.message)
    ) {
      return response?.status === 404
    }
  }

  return error instanceof Error && /conversation not found/i.test(error.message)
}

const localId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`

const toAssistantMessage = (
  response: CopilotAskResponse
): CopilotLocalMessage => ({
  id: response.message_id,
  role: "assistant",
  content: response.answer,
  summary: response.summary,
  confidence: response.confidence,
  questionType: response.question_type,
  domainsUsed: response.domains_used ?? [],
  toolsUsed: response.tools_used ?? [],
  evidence: response.evidence ?? [],
  missingData: response.missing_data ?? [],
  dataFreshness: response.data_freshness ?? [],
  recommendedNextSteps: response.recommended_next_steps ?? [],
  actionProposal: response.action_proposal ?? null,
  memoryCoverageWarning: response.memory_coverage_warning ?? null,
})

const toLocalMessages = (messages: CopilotMessage[]): CopilotLocalMessage[] =>
  messages.flatMap<CopilotLocalMessage>((message) => {
    if (message.role === "USER") {
      return [
        {
          id: message.id,
          role: "user" as const,
          content: message.content,
        },
      ]
    }

    if (message.role === "ASSISTANT") {
      const metadata = message.response_metadata_json ?? {}
      return [
        {
          id: message.id,
          role: "assistant" as const,
          content: message.answer ?? message.content,
          summary:
            message.summary ??
            (typeof metadata.summary === "string" ? metadata.summary : undefined),
          confidence:
            isConfidence(message.confidence)
              ? message.confidence
              : isConfidence(message.answer_confidence)
              ? message.answer_confidence
              : "MEDIUM",
          questionType:
            message.question_type ??
            (typeof metadata.question_type === "string"
              ? metadata.question_type
              : null),
          domainsUsed: message.domains_used?.length
            ? message.domains_used
            : normalizeStringList(message.domains_used_json),
          toolsUsed: message.tools_used?.length
            ? message.tools_used
            : normalizeToolUsage(message.tools_used_json),
          evidence: message.evidence?.length
            ? message.evidence
            : Array.isArray(message.evidence_json)
            ? (message.evidence_json as CopilotEvidence[])
            : [],
          missingData: message.missing_data?.length
            ? message.missing_data
            : normalizeMissingContext(
                message.missing_data_json ?? message.missing_context_json
              ),
          dataFreshness: message.data_freshness?.length
            ? message.data_freshness
            : normalizeFreshness(message.data_freshness_json),
          recommendedNextSteps: message.recommended_next_steps?.length
            ? message.recommended_next_steps
            : normalizeStringList(message.recommended_next_steps_json),
          actionProposal:
            message.action_proposal ??
            normalizeActionProposal(message.action_proposal_json),
          memoryCoverageWarning: null,
        },
      ]
    }

    return []
  })

const normalizeMissingContext = (value: unknown): CopilotMissingData[] => {
  if (Array.isArray(value)) {
    return value.map((item) =>
      typeof item === "string" ? { message: item } : (item as CopilotMissingData)
    )
  }

  if (
    value &&
    typeof value === "object" &&
    "missing_data" in value &&
    Array.isArray((value as { missing_data: unknown }).missing_data)
  ) {
    return normalizeMissingContext((value as { missing_data: unknown }).missing_data)
  }

  return []
}

const normalizeStringList = (value: unknown): string[] =>
  Array.isArray(value) ? value.map((item) => String(item)) : []

const normalizeToolUsage = (value: unknown): CopilotToolUsed[] =>
  Array.isArray(value)
    ? value.filter(
        (item): item is CopilotToolUsed =>
          Boolean(item) && typeof item === "object" && "status" in item
      )
    : []

const normalizeFreshness = (value: unknown): CopilotDataFreshness[] =>
  Array.isArray(value)
    ? value.filter(
        (item): item is CopilotDataFreshness =>
          Boolean(item) && typeof item === "object" && "status" in item
      )
    : []

const normalizeActionProposal = (value: unknown): CopilotActionProposal | null =>
  value && typeof value === "object" && "id" in value
    ? (value as CopilotActionProposal)
    : null

const isConfidence = (value: unknown): value is CopilotAskResponse["confidence"] =>
  value === "HIGH" ||
  value === "MEDIUM" ||
  value === "LOW" ||
  value === "NO_CONTEXT"

const latestConversation = (
  conversations: CopilotConversation[] | undefined
): CopilotConversation | undefined =>
  conversations
    ?.filter((conversation) => conversation.status !== "ARCHIVED")
    .sort(
      (left, right) =>
        new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime()
    )[0]

const dateRangeLabels: Record<string, string> = {
  today: "Today",
  yesterday: "Yesterday",
  last_7_days: "Last 7 days",
  last_30_days: "Last 30 days",
  this_month: "This month",
  last_month: "Last month",
  custom: "Custom range",
}

const domainLabels: Record<string, string> = {
  products: "Products",
  revenue: "Revenue",
  profit: "Profit",
  inventory: "Inventory",
  competitors: "Competitors",
  pricing: "Pricing",
  promotions: "Promotions",
  dead_stock: "Dead Stock",
  seo: "SEO",
  alerts: "Alerts",
  recommendations: "Recommendations",
  memory: "Memory",
}

const domainRequestValues: Record<string, CopilotDomain> = {
  products: "PRODUCT_CATALOG",
  revenue: "SALES_REVENUE",
  profit: "PROFIT_MARGIN",
  inventory: "INVENTORY",
  competitors: "COMPETITOR",
  pricing: "PRICING",
  promotions: "PROMOTION",
  dead_stock: "DEAD_STOCK",
  seo: "SEO_VISIBILITY",
  alerts: "ALERTS",
  recommendations: "RECOMMENDATIONS",
  memory: "RAG_MEMORY",
}

export function CopilotWidget() {
  const location = useLocation()
  const visible = shouldShowCopilotWidget(location.pathname)
  const [open, setOpen] = useState(false)
  const [conversationId, setConversationId] = useState<string | undefined>(
    () => copilotStorage.get() ?? undefined
  )
  const [messages, setMessages] = useState<CopilotLocalMessage[]>([])
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null)
  const [dateRange, setDateRange] = useState(() => resolveDateRange("last_7_days"))
  const [selectedDomains, setSelectedDomains] = useState<string[]>([])
  const [sourceMode, setSourceMode] = useState<CopilotSourceMode>("both")
  const [filtersExpanded, setFiltersExpanded] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const floatingButtonRef = useRef<HTMLButtonElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const ask = useAskCopilot()
  const conversations = useCopilotConversations(open && visible)
  const conversation = useCopilotConversation(conversationId, open && visible)
  const products = useProducts()
  const clearConversation = useCallback(
    (options: { clearMessages?: boolean } = {}) => {
      copilotStorage.remove()
      setConversationId(undefined)
      if (options.clearMessages) {
        setMessages([])
      }
    },
    []
  )

  useEffect(() => {
    if (open) {
      window.setTimeout(() => inputRef.current?.focus(), 120)
    } else {
      floatingButtonRef.current?.focus()
    }
  }, [open])

  useEffect(() => {
    if (!open || conversationId) {
      return
    }

    const storedConversationId = copilotStorage.get()
    if (storedConversationId) {
      window.setTimeout(() => setConversationId(storedConversationId), 0)
      return
    }

    const latest = latestConversation(conversations.data?.items)
    if (latest) {
      window.setTimeout(() => setConversationId(latest.id), 0)
    }
  }, [conversationId, conversations.data?.items, open])

  useEffect(() => {
    if (!conversationId) {
      return
    }

    copilotStorage.set(conversationId)
  }, [conversationId])

  useEffect(() => {
    if (
      !open ||
      !conversationId ||
      !conversation.isError ||
      !isCopilotConversationNotFoundError(conversation.error)
    ) {
      return
    }

    // Defer the reset so the query error can settle before changing the
    // conversation state from this effect.
    const resetTimeout = window.setTimeout(() => {
      clearConversation({ clearMessages: true })
    }, 0)

    return () => window.clearTimeout(resetTimeout)
  }, [
    clearConversation,
    conversation.error,
    conversation.isError,
    conversationId,
    open,
  ])

  useEffect(() => {
    if (!open || !conversation.data) {
      return
    }

    window.setTimeout(
      () => setMessages(toLocalMessages(conversation.data.messages)),
      0
    )
  }, [conversation.data, open])

  if (!visible) {
    return null
  }

  const close = () => setOpen(false)

  const handleProposalChange = (proposal: CopilotActionProposal) => {
    setMessages((current) =>
      current.map((message) => {
        if (
          message.role === "assistant" &&
          message.actionProposal?.id === proposal.id
        ) {
          return { ...message, actionProposal: proposal }
        }
        return message
      })
    )
  }

  const buildAskRequest = (
    question: string,
    activeConversationId?: string
  ): CopilotAskRequest => {
    const domainFilters = selectedDomains
      .map((domain) => domainRequestValues[domain])
      .filter((domain): domain is CopilotDomain => Boolean(domain))

    return {
      conversation_id: activeConversationId,
      question,
      product_id: selectedProductId || undefined,
      domain_filters: domainFilters,
      from_date: dateRange.fromDate,
      to_date: dateRange.toDate,
      language: "auto",
      include_current_data: sourceMode === "current" || sourceMode === "both",
      include_memory: sourceMode === "memory" || sourceMode === "both",
      top_k: 8,
    }
  }

  const submitQuestion = (question: string) => {
    if (ask.isPending) {
      return
    }

    const userMessage: CopilotLocalMessage = {
      id: localId(),
      role: "user",
      content: question,
    }

    setMessages((current) => [...current, userMessage])
    setErrorMessage(null)

    const sendQuestion = (activeConversationId?: string, retried = false) => {
      ask.mutate(buildAskRequest(question, activeConversationId), {
        onSuccess: (response) => {
          setConversationId(response.conversation_id)
          setMessages((current) => [...current, toAssistantMessage(response)])
        },
        onError: (error) => {
          if (
            activeConversationId &&
            !retried &&
            isCopilotConversationNotFoundError(error)
          ) {
            clearConversation()
            sendQuestion(undefined, true)
            return
          }

          setErrorMessage("Please try again.")
        },
      })
    }

    sendQuestion(conversationId)
  }

  const selectedProductTitle =
    products.data?.find((product) => product.id === selectedProductId)?.title ??
    (selectedProductId ? "Selected product" : "All products")
  const activeFilterSummary = [
    dateRangeLabels[dateRange.key] ?? "Custom range",
    selectedDomains.length
      ? selectedDomains.map((domain) => domainLabels[domain] ?? domain).join(", ")
      : "All domains",
    copilotSourceModes.find((mode) => mode.value === sourceMode)?.label ?? "Use both",
    selectedProductTitle,
  ].join(" · ")

  return (
    <>
      <CopilotFloatingButton
        ref={floatingButtonRef}
        open={open}
        onClick={() => setOpen(true)}
      />
      <CopilotChatPanel open={open} onClose={close}>
        <section className="border-b border-border/60 bg-card">
          <button
            type="button"
            className="flex w-full items-center gap-2 px-3 py-2 text-left transition hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
            aria-expanded={filtersExpanded}
            aria-controls="copilot-filter-content"
            onClick={() => setFiltersExpanded((current) => !current)}
          >
            <span className="text-sm font-semibold text-foreground">Filters</span>
            <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
              {activeFilterSummary}
            </span>
            <ChevronDown
              className={cn(
                "size-4 shrink-0 text-muted-foreground transition-transform duration-200",
                filtersExpanded ? "rotate-180" : ""
              )}
              aria-hidden="true"
            />
          </button>
          {filtersExpanded ? (
            <div
              id="copilot-filter-content"
              className="animate-in fade-in slide-in-from-top-1 duration-150"
            >
              <CopilotFilterControls
                dateRange={dateRange}
                selectedDomains={selectedDomains}
                sourceMode={sourceMode}
                onDateRangeChange={setDateRange}
                onDomainsChange={setSelectedDomains}
                onSourceModeChange={setSourceMode}
              />
              <div className="px-3 py-2">
                {conversations.data?.items?.length ? (
                  <label className="mb-2 block text-xs font-medium text-muted-foreground">
                    <span className="sr-only">Recent Copilot conversation</span>
                    <select
                      className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs text-foreground"
                      value={conversationId ?? ""}
                      onChange={(event) => {
                        setConversationId(event.target.value || undefined)
                        setMessages([])
                      }}
                      aria-label="Recent Copilot conversation"
                    >
                      {conversations.data.items.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.title ||
                            item.last_message_preview ||
                            "Untitled conversation"}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                <CopilotProductFilter
                  value={selectedProductId}
                  onChange={setSelectedProductId}
                />
              </div>
            </div>
          ) : null}
        </section>
        <div data-testid="copilot-message-area" className="flex min-h-0 flex-1 flex-col">
          {messages.length === 0 ? (
            <div className="flex-1 overflow-y-auto p-3">
              <CopilotEmptyState
                onSuggestedQuestion={submitQuestion}
                disabled={ask.isPending}
              />
              {errorMessage ? (
                <div className="mt-3">
                  <CopilotErrorState message={errorMessage} />
                </div>
              ) : null}
            </div>
          ) : (
            <>
              <CopilotMessageList
                messages={messages}
                isLoading={ask.isPending}
                onProposalChange={handleProposalChange}
              />
              {errorMessage ? (
                <div className="px-3 pb-2">
                  <CopilotErrorState message={errorMessage} />
                </div>
              ) : null}
            </>
          )}
          <CopilotQuestionInput
            ref={inputRef}
            disabled={ask.isPending}
            onSubmit={submitQuestion}
            onEscape={close}
          />
        </div>
      </CopilotChatPanel>
    </>
  )
}
