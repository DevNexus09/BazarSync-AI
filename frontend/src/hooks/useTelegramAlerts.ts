import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"

import {
  getTelegramAlertHistory,
} from "@/services/telegram-service"

const DEFAULT_PAGE_SIZE = 8

export function useTelegramAlerts() {
  const [page, setPage] = useState(1)
  const pageSize = DEFAULT_PAGE_SIZE

  const query = useQuery({
    queryKey: ["telegram", "alerts", page, pageSize],
    queryFn: ({ signal }) => getTelegramAlertHistory({ page, pageSize }, signal),
    staleTime: 15_000,
    retry: 1,
  })

  const alerts = useMemo(() => {
    const items = query.data?.items ?? []
    return items.filter((item) => item.isTelegram)
  }, [query.data?.items])

  return {
    alerts,
    meta: query.data?.meta,
    page,
    pageSize,
    setPage,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: query.refetch,
  }
}
