import { useQuery } from "@tanstack/react-query"

import { getCompetitors } from "../services/competitorService"

export const competitorsQueryKey = (productId: string) => [
  "competitors",
  productId,
]

export function useCompetitors(productId: string | null | undefined) {
  return useQuery({
    queryKey: productId ? competitorsQueryKey(productId) : ["competitors", "empty"],
    queryFn: () => getCompetitors(productId ?? ""),
    enabled: Boolean(productId),
    staleTime: 30_000,
    retry: 2,
  })
}
