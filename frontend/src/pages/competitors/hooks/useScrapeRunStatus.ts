import { useQuery } from "@tanstack/react-query"

import { getScrapeRunStatus } from "../services/competitorService"

export const scrapeRunStatusQueryKey = (scrapeRunId: string) => [
  "scrape-runs",
  scrapeRunId,
]

const normalizeStatus = (status?: string | null) => status?.toLowerCase()
const terminalStatuses = new Set(["completed", "failed", "partial"])

export function useScrapeRunStatus(scrapeRunId?: string | null) {
  return useQuery({
    queryKey: scrapeRunId
      ? scrapeRunStatusQueryKey(scrapeRunId)
      : ["scrape-runs", "empty"],
    queryFn: () => getScrapeRunStatus(scrapeRunId ?? ""),
    enabled: Boolean(scrapeRunId),
    refetchInterval: (query) => {
      const status = normalizeStatus(query.state.data?.status)
      if (!scrapeRunId) {
        return false
      }
      return status && terminalStatuses.has(status) ? false : 2000
    },
    staleTime: 0,
  })
}
