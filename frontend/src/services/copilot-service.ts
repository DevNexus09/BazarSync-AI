import apiClient from "@/api/client"
import type {
  CopilotActionProposal,
  CopilotActionProposalTransition,
  CopilotAskRequest,
  CopilotAskResponse,
  CopilotConversation,
  CopilotMessage,
  CopilotMissingData,
  CopilotToolMetadata,
} from "@/types/copilot"

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
  const payload = omitUndefined<CopilotAskRequest>({
    conversation_id: request.conversation_id,
    question: request.question,
    product_id: request.product_id || undefined,
    from_date: request.from_date || undefined,
    to_date: request.to_date || undefined,
    domain_filters: request.domain_filters?.length
      ? request.domain_filters
      : undefined,
    language: request.language ?? "auto",
    include_current_data: request.include_current_data ?? true,
    include_memory: request.include_memory ?? true,
    memory_source_types: request.memory_source_types?.length
      ? request.memory_source_types
      : undefined,
    top_k: request.top_k ?? 8,
  })

  if (request.debug === true && import.meta.env.DEV) {
    payload.debug = true
  }

  const { data } = await apiClient.post<BackendAskResponse>("/copilot/ask", payload)

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
  }
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
