import { useCallback, useEffect, useMemo, useRef } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { useSocketEvent } from "@/hooks/useSocketEvent"
import { getSocket } from "@/lib/socket"
import {
  phase5DashboardQueryKey,
  phase5MarketPositionQueryKey,
} from "@/hooks/usePhase5Dashboard"
import { RealtimeEventName, type Phase5RealtimeEvent } from "@/types/realtime"

type Options = {
  sellerId?: string
  productId?: string
  accessibleProductIds: string[]
  enabled?: boolean
}

type Phase5EventName =
  | typeof RealtimeEventName.CompetitorSnapshotCreated
  | typeof RealtimeEventName.CompetitorEventCreated
  | typeof RealtimeEventName.CompetitorRankingsUpdated
  | typeof RealtimeEventName.MarketOpportunityCreated
  | typeof RealtimeEventName.CompetitorSummaryUpdated

const isPhase5Payload = (
  payload: unknown,
  eventName: Phase5EventName
): payload is Phase5RealtimeEvent => {
  if (!payload || typeof payload !== "object") {
    return false
  }
  const value = payload as Partial<Phase5RealtimeEvent>
  return (
    value.version === 1 &&
    value.event === eventName &&
    typeof value.seller_id === "string" &&
    typeof value.product_id === "string" &&
    typeof value.occurred_at === "string" &&
    typeof value.data === "object" &&
    value.data !== null
  )
}

export function usePhase5RealtimeInvalidation({
  sellerId,
  productId,
  accessibleProductIds,
  enabled = true,
}: Options) {
  const queryClient = useQueryClient()
  const seenKeys = useRef<Set<string>>(new Set())
  const accessibleProducts = useMemo(
    () => new Set(accessibleProductIds),
    [accessibleProductIds]
  )

  const handlePhase5Event = useCallback(
    (
      eventName: Phase5EventName,
      payload: unknown
    ) => {
      if (!isPhase5Payload(payload, eventName)) {
        return
      }
      if (sellerId && payload.seller_id !== sellerId) {
        return
      }
      if (productId && payload.product_id !== productId) {
        return
      }
      if (
        accessibleProducts.size > 0 &&
        !accessibleProducts.has(payload.product_id)
      ) {
        return
      }
      const recordId =
        payload.data.event_id ??
        payload.data.opportunity_id ??
        payload.data.scrape_run_id ??
        payload.occurred_at
      const dedupeKey = `${payload.event}:${payload.product_id}:${String(recordId)}`
      if (seenKeys.current.has(dedupeKey)) {
        return
      }
      seenKeys.current.add(dedupeKey)
      if (seenKeys.current.size > 200) {
        const first = seenKeys.current.values().next().value
        if (first) {
          seenKeys.current.delete(first)
        }
      }
      queryClient.invalidateQueries({ queryKey: phase5DashboardQueryKey })
      queryClient.invalidateQueries({
        queryKey: phase5MarketPositionQueryKey(payload.product_id),
      })
    },
    [accessibleProducts, productId, queryClient, sellerId]
  )

  const handleSnapshot = useCallback(
    (payload: Phase5RealtimeEvent) =>
      handlePhase5Event(RealtimeEventName.CompetitorSnapshotCreated, payload),
    [handlePhase5Event]
  )
  const handleEvent = useCallback(
    (payload: Phase5RealtimeEvent) =>
      handlePhase5Event(RealtimeEventName.CompetitorEventCreated, payload),
    [handlePhase5Event]
  )
  const handleRankings = useCallback(
    (payload: Phase5RealtimeEvent) =>
      handlePhase5Event(RealtimeEventName.CompetitorRankingsUpdated, payload),
    [handlePhase5Event]
  )
  const handleOpportunity = useCallback(
    (payload: Phase5RealtimeEvent) =>
      handlePhase5Event(RealtimeEventName.MarketOpportunityCreated, payload),
    [handlePhase5Event]
  )
  const handleSummary = useCallback(
    (payload: Phase5RealtimeEvent) =>
      handlePhase5Event(RealtimeEventName.CompetitorSummaryUpdated, payload),
    [handlePhase5Event]
  )

  useSocketEvent(RealtimeEventName.CompetitorSnapshotCreated, handleSnapshot, {
    enabled,
  })
  useSocketEvent(RealtimeEventName.CompetitorEventCreated, handleEvent, {
    enabled,
  })
  useSocketEvent(RealtimeEventName.CompetitorRankingsUpdated, handleRankings, {
    enabled,
  })
  useSocketEvent(RealtimeEventName.MarketOpportunityCreated, handleOpportunity, {
    enabled,
  })
  useSocketEvent(RealtimeEventName.CompetitorSummaryUpdated, handleSummary, {
    enabled,
  })

  useEffect(() => {
    if (!enabled) {
      return
    }
    const socket = getSocket()
    const refetch = () => {
      queryClient.invalidateQueries({ queryKey: phase5DashboardQueryKey })
    }
    socket.io.on("reconnect", refetch)
    socket.on("connect", refetch)
    return () => {
      socket.io.off("reconnect", refetch)
      socket.off("connect", refetch)
    }
  }, [enabled, queryClient])
}
