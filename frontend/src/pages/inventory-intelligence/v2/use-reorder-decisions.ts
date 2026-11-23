import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useRef, useState } from "react"

import { inventoryIntelligenceKeys } from "@/hooks/useInventoryIntelligence"
import { setReorderRecommendationStatus } from "@/services/inventory-intelligence-service"

import { t } from "./inventory-i18n"

export type ReorderDecision = "mark-ordered" | "dismiss"
export type PendingDecision = { recommendationId: string; productName: string; decision: ReorderDecision }

export const UNDO_MS = 5000

/**
 * Optimistic reorder decisions with Undo. The API has no "reopen", so the call is held for
 * the undo window and sent only if not undone. Leaving the page sends pending calls at once.
 */
export function useReorderDecisions() {
  const queryClient = useQueryClient()
  const timers = useRef(new Map<string, { timer: number; pending: PendingDecision }>())
  const [pending, setPending] = useState<Record<string, ReorderDecision>>({})
  const [last, setLast] = useState<PendingDecision | null>(null)
  const [error, setError] = useState<string | null>(null)

  const forget = useCallback((id: string) => {
    timers.current.delete(id)
    setPending((current) => {
      const next = { ...current }
      delete next[id]
      return next
    })
  }, [])

  const commit = useCallback(
    async (item: PendingDecision) => {
      try {
        await setReorderRecommendationStatus(item.recommendationId, item.decision)
        await queryClient.invalidateQueries({ queryKey: inventoryIntelligenceKeys.all })
      } catch {
        setError(t("saveFailed", { name: item.productName }))
      } finally {
        forget(item.recommendationId)
      }
    },
    [forget, queryClient],
  )

  const decide = useCallback(
    (item: PendingDecision) => {
      setError(null)
      setPending((current) => ({ ...current, [item.recommendationId]: item.decision }))
      setLast(item)
      const timer = window.setTimeout(() => {
        timers.current.delete(item.recommendationId)
        setLast((current) => (current?.recommendationId === item.recommendationId ? null : current))
        void commit(item)
      }, UNDO_MS)
      timers.current.set(item.recommendationId, { timer, pending: item })
    },
    [commit],
  )

  const undo = useCallback(
    (recommendationId: string) => {
      const entry = timers.current.get(recommendationId)
      if (entry) window.clearTimeout(entry.timer)
      forget(recommendationId)
      setLast(null)
    },
    [forget],
  )

  useEffect(() => {
    const map = timers.current
    return () => {
      for (const { timer, pending: item } of map.values()) {
        window.clearTimeout(timer)
        void setReorderRecommendationStatus(item.recommendationId, item.decision)
      }
      map.clear()
    }
  }, [])

  return { pending, last, error, decide, undo, dismissError: () => setError(null) }
}

export type ReorderDecisions = ReturnType<typeof useReorderDecisions>
