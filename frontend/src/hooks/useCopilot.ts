import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  approveActionProposal,
  askCopilot,
  createCopilotConversation,
  getCopilotConversation,
  listActionProposals,
  listCopilotConversations,
  listCopilotTools,
  rejectActionProposal,
} from "@/services/copilot-service"
import type { CopilotAskRequest } from "@/types/copilot"

export const copilotQueryKeys = {
  conversations: ["copilot", "conversations"] as const,
  conversation: (conversationId: string) =>
    ["copilot", "conversation", conversationId] as const,
  tools: ["copilot", "tools"] as const,
  actionProposals: ["copilot", "action-proposals"] as const,
}

export function useCopilotConversations(enabled = true) {
  return useQuery({
    queryKey: copilotQueryKeys.conversations,
    queryFn: listCopilotConversations,
    enabled,
    staleTime: 60_000,
  })
}

export function useCreateCopilotConversation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createCopilotConversation,
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: copilotQueryKeys.conversations,
      }),
  })
}

export function useCopilotConversation(conversationId?: string, enabled = true) {
  return useQuery({
    queryKey: conversationId
      ? copilotQueryKeys.conversation(conversationId)
      : ["copilot", "conversation", "none"],
    queryFn: () => {
      if (!conversationId) {
        return Promise.reject(new Error("Conversation id is required"))
      }
      return getCopilotConversation(conversationId)
    },
    enabled: enabled && Boolean(conversationId),
    staleTime: 30_000,
  })
}

export function useAskCopilot() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (request: CopilotAskRequest) => askCopilot(request),
    onSuccess: (response) => {
      queryClient.invalidateQueries({
        queryKey: copilotQueryKeys.conversations,
      })
      queryClient.invalidateQueries({
        queryKey: copilotQueryKeys.conversation(response.conversation_id),
      })
      queryClient.invalidateQueries({
        queryKey: copilotQueryKeys.actionProposals,
      })
    },
  })
}

export function useCopilotTools() {
  return useQuery({
    queryKey: copilotQueryKeys.tools,
    queryFn: listCopilotTools,
    staleTime: 5 * 60_000,
  })
}

export function useActionProposals() {
  return useQuery({
    queryKey: copilotQueryKeys.actionProposals,
    queryFn: listActionProposals,
    staleTime: 30_000,
  })
}

export function useApproveActionProposal() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: approveActionProposal,
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: copilotQueryKeys.actionProposals,
      }),
  })
}

export function useRejectActionProposal() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: rejectActionProposal,
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: copilotQueryKeys.actionProposals,
      }),
  })
}
