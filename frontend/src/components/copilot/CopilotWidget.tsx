import { useCallback, useEffect, useRef, useState } from "react"
import { History, SquarePen } from "lucide-react"
import { useLocation } from "react-router-dom"

import { CopilotChatPanel } from "@/components/copilot/CopilotChatPanel"
import { CopilotEmptyState } from "@/components/copilot/CopilotEmptyState"
import { CopilotErrorState } from "@/components/copilot/CopilotErrorState"
import { CopilotFloatingButton } from "@/components/copilot/CopilotFloatingButton"
import { CopilotMessageList } from "@/components/copilot/CopilotMessageList"
import { CopilotQuestionInput } from "@/components/copilot/CopilotQuestionInput"
import { shouldShowCopilotWidget } from "@/components/copilot/copilot-visibility"
import {
  classifyCopilotError,
  errorText,
  languageOptions,
  resolveUiLanguage,
  t,
  type CopilotErrorKind,
} from "@/components/copilot/copilot-i18n"
import {
  useAskCopilot,
  useCopilotConversation,
  useCopilotConversations,
  useCopilotFeatures,
  useCopilotFeedback,
} from "@/hooks/useCopilot"
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
  CopilotFeedbackRating,
  CopilotLanguage,
  CopilotReplyLanguage,
  CopilotStreamStage,
} from "@/types/copilot"

const conversationStorageKey = "bazarsync:copilot:conversation-id"
const languageStorageKey = "bazarsync:copilot:language"

const languagePreference = {
  get(): CopilotLanguage {
    try {
      const value = window.localStorage?.getItem(languageStorageKey)
      return value === "en" || value === "bn" || value === "banglish" ? value : "auto"
    } catch {
      return "auto"
    }
  },
  set(value: CopilotLanguage) {
    try {
      window.localStorage?.setItem(languageStorageKey, value)
    } catch {
      // The choice still applies for this session.
    }
  },
}

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
  replyLanguage: response.reply_language ?? null,
  replyScript: response.reply_script ?? null,
  followUps: response.suggested_follow_ups ?? [],
  feedback: null,
})

const isReplyLanguage = (value: unknown): value is CopilotReplyLanguage =>
  value === "en" || value === "bn" || value === "banglish"

const storedReplyLanguage = (metadata: Record<string, unknown>): CopilotReplyLanguage | null => {
  const profile = metadata.language_profile
  if (profile && typeof profile === "object") {
    const value = (profile as { reply_language?: unknown }).reply_language
    return isReplyLanguage(value) ? value : null
  }
  return null
}

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
          replyLanguage: storedReplyLanguage(metadata),
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

export function CopilotWidget() {
  const location = useLocation()
  const visible = shouldShowCopilotWidget(location.pathname)
  const [open, setOpen] = useState(false)
  const [conversationId, setConversationId] = useState<string | undefined>(
    () => copilotStorage.get() ?? undefined
  )
  const [messages, setMessages] = useState<CopilotLocalMessage[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  // After "New chat" the widget must not jump back to the latest stored conversation.
  const [freshChat, setFreshChat] = useState(false)
  const [language, setLanguage] = useState<CopilotLanguage>(() => languagePreference.get())
  const [stage, setStage] = useState<CopilotStreamStage | null>(null)
  const [failure, setFailure] = useState<{ question: string; kind: CopilotErrorKind } | null>(null)
  const [restore, setRestore] = useState<{ text: string; nonce: number } | null>(null)
  const floatingButtonRef = useRef<HTMLButtonElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const ask = useAskCopilot()
  const feedback = useCopilotFeedback()
  const features = useCopilotFeatures(open && visible)
  const conversations = useCopilotConversations(open && visible)
  const conversation = useCopilotConversation(conversationId, open && visible)
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
    if (!open || conversationId || freshChat) {
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
  }, [conversationId, conversations.data?.items, freshChat, open])

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
      () =>
        setMessages((current) => {
          const hydrated = toLocalMessages(conversation.data.messages)
          // Keep follow-ups and feedback chosen in this session when the server copy refreshes.
          const local = new Map(
            current.flatMap((message) => (message.role === "assistant" ? [[message.id, message] as const] : []))
          )
          return hydrated.map((message) => {
            const previous = message.role === "assistant" ? local.get(message.id) : undefined
            return previous && previous.role === "assistant" && message.role === "assistant"
              ? { ...message, followUps: previous.followUps, feedback: previous.feedback, replyLanguage: previous.replyLanguage ?? message.replyLanguage }
              : message
          })
        }),
      0
    )
  }, [conversation.data, open])

  if (!visible) {
    return null
  }

  const supportedLanguages = features.data?.languages ?? ["auto", "en", "bn"]
  const activeLanguage: CopilotLanguage = supportedLanguages.includes(language) ? language : "auto"
  const lastReply = [...messages].reverse().find((message) => message.role === "assistant")
  const uiLanguage = resolveUiLanguage(
    activeLanguage,
    lastReply?.role === "assistant" ? lastReply.replyLanguage : null
  )

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

  // No filters: the backend reads dates, products and scope from the question itself.
  const buildAskRequest = (
    question: string,
    activeConversationId?: string
  ): CopilotAskRequest => ({
    conversation_id: activeConversationId,
    question,
    language: activeLanguage,
  })

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
    setFailure(null)
    setHistoryOpen(false)
    const streaming = Boolean(features.data?.streaming)
    setStage(streaming ? { stage: "understanding" } : null)

    const sendQuestion = (activeConversationId?: string, retried = false) => {
      ask.mutate(
        {
          request: buildAskRequest(question, activeConversationId),
          onStage: streaming ? setStage : undefined,
        },
        {
          onSuccess: (response) => {
            setStage(null)
            setFreshChat(false)
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

            setStage(null)
            setMessages((current) =>
              current.map((message) =>
                message.id === userMessage.id ? { ...message, failed: true } : message
              )
            )
            setFailure({ question, kind: classifyCopilotError(error) })
            // Keep the seller's words: put the question back so it can be edited or resent.
            setRestore({ text: question, nonce: Date.now() })
          },
        }
      )
    }

    sendQuestion(conversationId)
  }

  const retryFailedQuestion = () => {
    if (!failure) {
      return
    }
    const question = failure.question
    setMessages((current) =>
      current.filter((message) => !(message.role === "user" && message.failed && message.content === question))
    )
    setRestore({ text: "", nonce: Date.now() })
    submitQuestion(question)
  }

  const startNewChat = () => {
    clearConversation({ clearMessages: true })
    setFreshChat(true)
    setFailure(null)
    setHistoryOpen(false)
    window.setTimeout(() => inputRef.current?.focus(), 0)
  }

  const openConversation = (id: string) => {
    // Re-picking the open chat would clear messages without a refetch to restore them.
    if (id === conversationId) {
      setHistoryOpen(false)
      return
    }
    setFreshChat(false)
    setConversationId(id)
    setMessages([])
    setFailure(null)
    setHistoryOpen(false)
  }

  const regenerate = (assistantMessageId: string) => {
    const index = messages.findIndex((message) => message.id === assistantMessageId)
    const question = [...messages.slice(0, index)].reverse().find((message) => message.role === "user")
    if (question) {
      submitQuestion(question.content)
    }
  }

  const rateAnswer = (messageId: string, rating: CopilotFeedbackRating) => {
    const setRating = (value: CopilotFeedbackRating | null) =>
      setMessages((current) =>
        current.map((message) =>
          message.role === "assistant" && message.id === messageId ? { ...message, feedback: value } : message
        )
      )
    const previous = messages.find((message) => message.id === messageId)
    setRating(rating)
    feedback.mutate(
      { messageId, rating },
      { onError: () => setRating(previous?.role === "assistant" ? previous.feedback ?? null : null) }
    )
  }

  const changeLanguage = (value: CopilotLanguage) => {
    setLanguage(value)
    languagePreference.set(value)
  }

  const headerActions = (
    <div className="flex items-center gap-0.5">
      <label className="sr-only" htmlFor="copilot-language">
        {t(uiLanguage, "language")}
      </label>
      <select
        id="copilot-language"
        aria-label="Reply language"
        title={t(uiLanguage, "language")}
        value={activeLanguage}
        onChange={(event) => changeLanguage(event.target.value as CopilotLanguage)}
        className="h-8 rounded-md border border-border/70 bg-background px-1.5 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
      >
        {languageOptions
          .filter((option) => supportedLanguages.includes(option.value))
          .map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
      </select>
      <button
        type="button"
        aria-label={t(uiLanguage, "history")}
        title={t(uiLanguage, "history")}
        aria-expanded={historyOpen}
        aria-controls="copilot-history"
        onClick={() => setHistoryOpen((current) => !current)}
        className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
      >
        <History className="size-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label={t(uiLanguage, "newChat")}
        title={t(uiLanguage, "newChat")}
        onClick={startNewChat}
        disabled={ask.isPending}
        className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:opacity-40"
      >
        <SquarePen className="size-4" aria-hidden="true" />
      </button>
    </div>
  )

  const errorBox = failure ? (
    <CopilotErrorState
      title={t(uiLanguage, "errorTitle")}
      message={errorText(failure.kind, uiLanguage)}
      retryLabel={t(uiLanguage, "retry")}
      onRetry={ask.isPending ? undefined : retryFailedQuestion}
    />
  ) : null

  return (
    <>
      <CopilotFloatingButton
        ref={floatingButtonRef}
        open={open}
        onClick={() => setOpen(true)}
      />
      <CopilotChatPanel
        open={open}
        onClose={close}
        expanded={expanded}
        onToggleExpanded={() => setExpanded((current) => !current)}
        title={t(uiLanguage, "title")}
        subtitle={t(uiLanguage, "subtitle")}
        actions={headerActions}
      >
        {historyOpen ? (
          <nav
            id="copilot-history"
            aria-label={t(uiLanguage, "history")}
            className="max-h-56 overflow-y-auto border-b border-border/60 bg-background/70 p-2"
          >
            {conversations.data?.items?.length ? (
              <ul className="space-y-1">
                {conversations.data.items.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => openConversation(item.id)}
                      aria-current={item.id === conversationId ? "true" : undefined}
                      className={cn(
                        "w-full truncate rounded-md px-2 py-1.5 text-left text-xs transition hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30",
                        item.id === conversationId ? "bg-primary/10 font-medium text-foreground" : "text-muted-foreground"
                      )}
                    >
                      {item.title || item.last_message_preview || t(uiLanguage, "untitled")}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-2 py-1.5 text-xs text-muted-foreground">{t(uiLanguage, "noHistory")}</p>
            )}
          </nav>
        ) : null}
        <div data-testid="copilot-message-area" className="flex min-h-0 flex-1 flex-col">
          {messages.length === 0 ? (
            <div className="copilot-scroll flex-1 overflow-y-auto p-3">
              <div className="copilot-column">
                <CopilotEmptyState />
                {errorBox ? <div className="mt-3">{errorBox}</div> : null}
              </div>
            </div>
          ) : (
            <>
              <CopilotMessageList
                messages={messages}
                isLoading={ask.isPending}
                stage={stage}
                onProposalChange={handleProposalChange}
                language={uiLanguage}
                actions={{
                  onRegenerate: regenerate,
                  onFeedback: features.data?.feedback ? rateAnswer : undefined,
                  onFollowUp: submitQuestion,
                  disabled: ask.isPending,
                }}
              />
              {errorBox ? <div className="px-3 pb-2">{errorBox}</div> : null}
            </>
          )}
          <CopilotQuestionInput
            ref={inputRef}
            disabled={ask.isPending}
            onSubmit={submitQuestion}
            onEscape={close}
            placeholder={t(uiLanguage, "inputPlaceholder")}
            hint={t(uiLanguage, "inputHint")}
            restore={restore}
          />
        </div>
      </CopilotChatPanel>
    </>
  )
}
