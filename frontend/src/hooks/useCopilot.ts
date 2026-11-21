import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  approveActionProposal,
  askCopilot,
  askCopilotStream,
  getCopilotFeatures,
  submitCopilotFeedback,
  createCopilotConversation,
  getCopilotConversation,
  listActionProposals,
  listCopilotConversations,
  listCopilotTools,
  rejectActionProposal,
} from "@/services/copilot-service"
import type {
  CopilotAskRequest,
  CopilotFeedbackRating,
  CopilotStreamStage,
} from "@/types/copilot"

export const copilotQueryKeys = {
  conversations: ["copilot", "conversations"] as const,
  conversation: (conversationId: string) =>
    ["copilot", "conversation", conversationId] as const,
  tools: ["copilot", "tools"] as const,
  actionProposals: ["copilot", "action-proposals"] as const,
  features: ["copilot", "features"] as const,
}

export function useCopilotFeatures(enabled = true) {
  return useQuery({
    queryKey: copilotQueryKeys.features,
    queryFn: getCopilotFeatures,
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function useCopilotFeedback() {
  return useMutation({
    mutationFn: ({ messageId, rating }: { messageId: string; rating: CopilotFeedbackRating }) =>
      submitCopilotFeedback(messageId, rating),
  })
}

export type CopilotAskVariables = {
  request: CopilotAskRequest
  /** Set when the backend advertises streaming; receives progress stages. */
  onStage?: (stage: CopilotStreamStage) => void
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
    mutationFn: ({ request, onStage }: CopilotAskVariables) =>
      onStage ? askCopilotStream(request, onStage) : askCopilot(request),
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
