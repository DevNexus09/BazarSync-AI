import { useQuery } from "@tanstack/react-query"

import { getScrapeRunStatus } from "../services/competitorService"

export const scrapeRunStatusQueryKey = (scrapeRunId: string) => [
  "scrape-runs",
  scrapeRunId,
]

export function useScrapeRunStatus(scrapeRunId?: string | null) {
  return useQuery({
    queryKey: scrapeRunId
      ? scrapeRunStatusQueryKey(scrapeRunId)
      : ["scrape-runs", "empty"],
    queryFn: () => getScrapeRunStatus(scrapeRunId ?? ""),
    enabled: Boolean(scrapeRunId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === "pending" || status === "running" ? 5000 : false
    },
    staleTime: 0,
  })
}
