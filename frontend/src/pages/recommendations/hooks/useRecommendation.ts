import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useMemo } from "react"

import { getErrorMessage } from "@/utils/errors"

import {
  generateRecommendation,
  getLatestRecommendation,
} from "../services/recommendationApi"
import type { RecommendationData } from "../types/recommendation"

const recommendationQueryKey = (productId: string) => [
  "recommendations",
  productId,
]

export function useRecommendation(productId: string | null | undefined) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: productId ? recommendationQueryKey(productId) : ["recommendations", "empty"],
    queryFn: () => getLatestRecommendation(productId ?? ""),
    enabled: Boolean(productId),
    staleTime: 30_000,
    retry: 1,
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
      queryClient.setQueryData(recommendationQueryKey(productId), payload)
    },
  })
  const data = useMemo<RecommendationData | null>(() => {
    if (!productId) {
      return null
    }
    if (mutation.data && mutation.data.productId === productId) {
      return mutation.data
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
    isGenerating: mutation.isPending,
    isFetching: query.isFetching,
    isError: mutation.isError || query.isError,
    error: mutation.error ?? query.error,
    errorMessage,
    generateRecommendation: mutation.mutate,
    reset: mutation.reset,
  }
}
