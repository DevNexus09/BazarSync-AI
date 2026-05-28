import { useQuery } from "@tanstack/react-query"

import { getCompetitors } from "@/services/dashboard-service"

export const competitorsQueryKey = ["war-room", "competitors"]

export function useCompetitors() {
  return useQuery({
    queryKey: competitorsQueryKey,
    queryFn: ({ signal }) => getCompetitors(signal),
    staleTime: 20_000,
    retry: 2,
  })
}
