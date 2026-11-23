import apiClient from "@/api/client"
import { getAuthToken } from "@/services/auth-storage"
import type {
  CopilotActionProposal,
  CopilotActionProposalTransition,
  CopilotAskPayload,
  CopilotAskRequest,
  CopilotAskResponse,
  CopilotConversation,
  CopilotFeatures,
  CopilotFeedbackRating,
  CopilotMessage,
  CopilotMissingData,
  CopilotStreamStage,
  CopilotToolMetadata,
} from "@/types/copilot"
import { env } from "@/utils/env"

type Paginated<T> = {
  items: T[]
  total: number
  limit: number
  offset: number
}

type ConversationDetail = {
  conversation: CopilotConversation
  messages: CopilotMessage[]
}

type BackendAskResponse = Omit<CopilotAskResponse, "missing_data"> & {
  missing_data?: Array<string | CopilotMissingData>
}

type BackendActionProposal = {
  id: string
  action_type: string
  status: string
  requires_confirmation: boolean
  proposed_payload_json?: Record<string, unknown>
  safety_checks_json?: unknown
  expected_impact_json?: unknown
  evidence_json?: unknown
}

const normalizeMissingData = (
  missingData?: Array<string | CopilotMissingData>
): CopilotMissingData[] =>
  (missingData ?? []).map((item) =>
    typeof item === "string" ? { message: item } : item
  )

const mapActionProposal = (
  proposal: BackendActionProposal | CopilotActionProposal | null | undefined
): CopilotActionProposal | null => {
  if (!proposal) {
    return null
  }

  if ("proposed_payload_json" in proposal) {
    const payload = proposal.proposed_payload_json ?? {}
    return {
      id: proposal.id,
      action_type: proposal.action_type,
      status: proposal.status,
      summary:
        typeof payload.summary === "string"
          ? payload.summary
          : "Proposal saved for seller confirmation.",
      requires_confirmation: proposal.requires_confirmation,
      safety_checks: proposal.safety_checks_json,
      expected_impact: proposal.expected_impact_json,
      evidence: proposal.evidence_json,
    }
  }

  return proposal
}

const mapUnknownActionProposal = (value: unknown): CopilotActionProposal | null =>
  value && typeof value === "object"
    ? mapActionProposal(value as BackendActionProposal | CopilotActionProposal)
    : null

const normalizeConversation = (
  conversation: CopilotConversation
): CopilotConversation => ({
  ...conversation,
  id: conversation.id || conversation.conversation_id || "",
  conversation_id: conversation.conversation_id || conversation.id,
})

export async function listCopilotConversations(): Promise<
  Paginated<CopilotConversation>
> {
  const { data } = await apiClient.get<Paginated<CopilotConversation>>(
    "/copilot/conversations"
  )
  return { ...data, items: data.items.map(normalizeConversation) }
}

export async function createCopilotConversation(input: {
  title?: string
  language?: "bn" | "en"
}): Promise<CopilotConversation> {
  const { data } = await apiClient.post<CopilotConversation>(
    "/copilot/conversations",
    input
  )
  return normalizeConversation(data)
}

export async function getCopilotConversation(
  conversationId: string
): Promise<ConversationDetail> {
  const { data } = await apiClient.get<ConversationDetail>(
    `/copilot/conversations/${conversationId}`
  )
  return {
    conversation: normalizeConversation(data.conversation),
    messages: data.messages.map((message) => ({
      ...message,
      action_proposal: mapActionProposal(
        message.action_proposal
      ) ?? mapUnknownActionProposal(
        message.action_proposal_json
      ),
      missing_data: normalizeMissingData(
        message.missing_data ??
          (Array.isArray(message.missing_data_json)
            ? (message.missing_data_json as Array<string | CopilotMissingData>)
            : undefined)
      ),
    })),
  }
}

export async function askCopilot(
  request: CopilotAskRequest
): Promise<CopilotAskResponse> {
  const { data } = await apiClient.post<BackendAskResponse>(
    "/copilot/ask",
    buildAskPayload(request)
  )
  return normalizeAskResponse(data)
}

function buildAskPayload(request: CopilotAskRequest): CopilotAskPayload {
  // The backend still accepts filter fields; the client sends none and always uses data + memory.
  const payload = omitUndefined<CopilotAskPayload>({
    conversation_id: request.conversation_id,
    question: request.question,
    language: request.language ?? "auto",
    include_current_data: true,
    include_memory: true,
  })

  if (request.debug === true && import.meta.env.DEV) {
    payload.debug = true
  }
  return payload
}

function normalizeAskResponse(data: BackendAskResponse): CopilotAskResponse {
  return {
    ...data,
    domains_used: data.domains_used ?? [],
    tools_used: data.tools_used ?? [],
    evidence: data.evidence ?? [],
    missing_data: normalizeMissingData(data.missing_data),
    data_freshness: data.data_freshness ?? [],
    recommended_next_steps: data.recommended_next_steps ?? [],
    action_proposal: mapActionProposal(data.action_proposal),
    memory_coverage_warning: data.memory_coverage_warning ?? null,
    suggested_follow_ups: data.suggested_follow_ups ?? [],
  }
}

/** Error shaped like an axios error so the widget can classify stream failures the same way. */
export class CopilotStreamError extends Error {
  response?: { status: number; data?: unknown; headers?: Record<string, string> }
  code?: string

  constructor(
    message: string,
    options: { status?: number; data?: unknown; code?: string; retryAfter?: string | null } = {}
  ) {
    super(message)
    this.name = "CopilotStreamError"
    this.code = options.code
    if (options.status !== undefined) {
      this.response = {
        status: options.status,
        data: options.data,
        headers: options.retryAfter ? { "retry-after": options.retryAfter } : {},
      }
    }
  }
}

const STREAM_TIMEOUT_MS = 60_000

/**
 * POST /copilot/ask/stream: calls ``onStage`` for each progress event and resolves with the
 * final validated answer (the same body /copilot/ask returns). Answer text is never streamed
 * before the backend has validated it.
 */
export async function askCopilotStream(
  request: CopilotAskRequest,
  onStage: (stage: CopilotStreamStage) => void,
  options: { signal?: AbortSignal } = {}
): Promise<CopilotAskResponse> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), STREAM_TIMEOUT_MS)
  options.signal?.addEventListener("abort", () => controller.abort())
  const token = readAuthToken()
  try {
    let response: Response
    try {
      response = await fetch(`${env.apiBaseUrl}/copilot/ask/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(buildAskPayload(request)),
        signal: controller.signal,
      })
    } catch (error) {
      throw controller.signal.aborted
        ? new CopilotStreamError("Copilot request timed out.", { code: "ECONNABORTED" })
        : new CopilotStreamError(error instanceof Error ? error.message : "Network error", { code: "ERR_NETWORK" })
    }
    if (!response.ok || !response.body) {
      let data: unknown = undefined
      try {
        data = await response.json()
      } catch {
        // Non-JSON error body; the status code is enough to classify it.
      }
      throw new CopilotStreamError(`Request failed with status code ${response.status}`, {
        status: response.status,
        data,
        retryAfter: response.headers.get("retry-after"),
      })
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    for (;;) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
      let boundary = buffer.indexOf("\n\n")
      while (boundary !== -1) {
        const event = parseSseEvent(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        if (event?.name === "stage") {
          onStage(event.data as CopilotStreamStage)
        } else if (event?.name === "answer") {
          return normalizeAskResponse(event.data as BackendAskResponse)
        } else if (event?.name === "error") {
          const detail = event.data as { error_code?: string; detail?: string }
          throw new CopilotStreamError(detail.detail ?? "Copilot could not answer right now.", {
            status: detail.error_code === "conversation_not_found" ? 404 : 500,
            data: { detail },
          })
        }
        boundary = buffer.indexOf("\n\n")
      }
      if (done) {
        break
      }
    }
    throw new CopilotStreamError("The Copilot stream ended without an answer.", { status: 502 })
  } finally {
    window.clearTimeout(timeout)
  }
}

function readAuthToken(): string | null {
  try {
    return getAuthToken()
  } catch {
    // Storage can be blocked (privacy mode); the backend then answers 401.
    return null
  }
}

function parseSseEvent(block: string): { name: string; data: unknown } | null {
  let name = "message"
  const dataLines: string[] = []
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      name = line.slice(6).trim()
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart())
    }
  }
  if (!dataLines.length) {
    return null
  }
  try {
    return { name, data: JSON.parse(dataLines.join("\n")) }
  } catch {
    return null
  }
}

export async function getCopilotFeatures(): Promise<CopilotFeatures> {
  // The backend returns {status, capabilities: {features, ...}}.
  const { data } = await apiClient.get<{
    capabilities?: { features?: Partial<CopilotFeatures> }
  }>("/copilot/capabilities")
  const features = data.capabilities?.features
  return {
    multilingual: Boolean(features?.multilingual),
    languages: features?.languages ?? ["auto", "en", "bn"],
    streaming: Boolean(features?.streaming),
    follow_ups: Boolean(features?.follow_ups),
    feedback: Boolean(features?.feedback),
    conversation_memory: Boolean(features?.conversation_memory),
  }
}

export async function submitCopilotFeedback(
  messageId: string,
  rating: CopilotFeedbackRating,
  reason?: string
): Promise<{ message_id: string; rating: CopilotFeedbackRating }> {
  const { data } = await apiClient.post<{ message_id: string; rating: CopilotFeedbackRating }>(
    `/copilot/messages/${messageId}/feedback`,
    omitUndefined({ rating, reason })
  )
  return data
}

function omitUndefined<T extends Record<string, unknown>>(value: T): T {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => item !== undefined)
  ) as T
}

export async function listCopilotTools(): Promise<CopilotToolMetadata[]> {
  const { data } = await apiClient.get<{ tools: CopilotToolMetadata[] }>(
    "/copilot/tools"
  )
  return data.tools
}

export async function listActionProposals(): Promise<
  Paginated<CopilotActionProposal>
> {
  const { data } = await apiClient.get<Paginated<BackendActionProposal>>(
    "/copilot/action-proposals"
  )
  return {
    ...data,
    items: data.items
      .map((proposal) => mapActionProposal(proposal))
      .filter((proposal): proposal is CopilotActionProposal => Boolean(proposal)),
  }
}

export async function approveActionProposal(
  proposalId: string
): Promise<CopilotActionProposalTransition> {
  const { data } = await apiClient.post<{
    proposal: BackendActionProposal
    message: string
    executed: boolean
  }>(`/copilot/action-proposals/${proposalId}/approve`)
  return {
    proposal: mapActionProposal(data.proposal) as CopilotActionProposal,
    message: data.message,
    executed: data.executed,
  }
}

export async function rejectActionProposal(
  proposalId: string
): Promise<CopilotActionProposalTransition> {
  const { data } = await apiClient.post<{
    proposal: BackendActionProposal
    message: string
    executed: boolean
  }>(`/copilot/action-proposals/${proposalId}/reject`)
  return {
    proposal: mapActionProposal(data.proposal) as CopilotActionProposal,
    message: data.message,
    executed: data.executed,
  }
}
