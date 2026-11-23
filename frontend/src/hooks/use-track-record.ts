import { useQuery } from "@tanstack/react-query"

import { getTrackRecord, type OutcomeType } from "@/services/recommendation-outcome-service"

export function useTrackRecord(type: OutcomeType) {
  return useQuery({
    queryKey: ["recommendation-outcomes", "track-record", type],
    queryFn: () => getTrackRecord(type),
    staleTime: 10 * 60_000,
    retry: false,
  })
}
