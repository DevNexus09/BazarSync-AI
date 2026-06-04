import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useMemo, useState } from "react"

import { getErrorMessage } from "@/utils/errors"

import {
  generateRecommendation,
  getLatestRecommendation,
} from "../services/recommendationApi"
import type {
  RecommendationData,
  RecommendationQueuedResult,
} from "../types/recommendation"

const recommendationQueryKey = (productId: string) => [
  "recommendations",
  productId,
]

export function useRecommendation(productId: string | null | undefined) {
  const queryClient = useQueryClient()
  const [queuedTask, setQueuedTask] = useState<{
    task: RecommendationQueuedResult
    queuedAt: number
  } | null>(null)
  const query = useQuery({
    queryKey: productId ? recommendationQueryKey(productId) : ["recommendations", "empty"],
    queryFn: () => getLatestRecommendation(productId ?? ""),
    enabled: Boolean(productId),
    staleTime: 30_000,
    retry: 1,
    refetchInterval: (queryState) => {
      if (!queuedTask) {
        return false
      }
      const data = queryState.state.data
      if (!data?.createdAt) {
        return 5000
      }
      const createdAt = new Date(data.createdAt).getTime()
      if (Number.isNaN(createdAt) || createdAt < queuedTask.queuedAt) {
        return 5000
      }
      return false
    },
  })

  const mutation = useMutation({
    mutationFn: async () => {
      if (!productId) {
        throw new Error("Select a product to generate recommendations.")
      }
      return generateRecommendation(productId)
    },
    onSuccess: (payload) => {
      if (!productId) {
        return
      }
      if ("queued" in payload && payload.queued) {
        setQueuedTask({ task: payload, queuedAt: Date.now() })
        queryClient.invalidateQueries({
          queryKey: recommendationQueryKey(productId),
        })
        return
      }
      setQueuedTask(null)
      queryClient.setQueryData(recommendationQueryKey(productId), payload)
    },
  })
  const isQueued = (() => {
    if (!queuedTask) {
      return false
    }
    if (!query.data?.createdAt) {
      return true
    }
    const createdAt = new Date(query.data.createdAt).getTime()
    if (Number.isNaN(createdAt)) {
      return true
    }
    return createdAt < queuedTask.queuedAt
  })()
  const data = useMemo<RecommendationData | null>(() => {
    if (!productId) {
      return null
    }
    const resolvedMutationData =
      mutation.data && "queued" in mutation.data ? null : mutation.data
    if (resolvedMutationData && resolvedMutationData.productId === productId) {
      return resolvedMutationData
    }
    if (query.data && query.data.productId === productId) {
      return query.data
    }
    return null
  }, [mutation.data, productId, query.data])

  const errorMessage = useMemo(() => {
    if (mutation.isError) {
      return getErrorMessage(
        mutation.error,
        "Recommendation generation failed. Please try again."
      )
    }
    if (query.isError) {
      return getErrorMessage(
        query.error,
        "We couldn't load your latest recommendation."
      )
    }
    return null
  }, [mutation.isError, mutation.error, query.isError, query.error])

  return {
    data,
    isLoading: mutation.isPending || (query.isLoading && !mutation.data),
    isGenerating: mutation.isPending || isQueued,
    isFetching: query.isFetching,
    isError: mutation.isError || query.isError,
    error: mutation.error ?? query.error,
    errorMessage,
    isQueued,
    queuedTaskId: queuedTask?.task.taskId ?? null,
    generateRecommendation: mutation.mutate,
    reset: mutation.reset,
  }
}
