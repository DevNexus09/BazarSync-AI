import { useMutation, useQueryClient } from "@tanstack/react-query"

import { runScraper } from "../services/competitorService"
import { competitorsQueryKey } from "./useCompetitors"

export function useRunScraper(productId: string | null | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async () => {
      if (!productId) {
        throw new Error("Select a product before running the scraper.")
      }
      return runScraper(productId)
    },
    onSuccess: () => {
      if (!productId) {
        return
      }
      queryClient.invalidateQueries({ queryKey: competitorsQueryKey(productId) })
    },
  })
}
