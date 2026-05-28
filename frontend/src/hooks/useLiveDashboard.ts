import { useCallback, useMemo, useRef } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { useRealtime } from "@/hooks/useRealtime"
import { useSocketEvent } from "@/hooks/useSocketEvent"
import {
  activityQueryKey,
  marketOpportunitiesQueryKey,
  recommendationsQueryKey,
  summaryQueryKey,
} from "@/hooks/useDashboard"
import { competitorsQueryKey } from "@/hooks/useCompetitors"
import {
  activeAlertsQueryKey,
  alertHistoryQueryKey,
  alertSummaryQueryKey,
} from "@/hooks/useAlerts"
import {
  ActivitySeverity,
  type ActivityItem,
  type DashboardSummary,
} from "@/types/dashboard"
import {
  AlertSeverity,
  type Alert,
  type AlertSummary,
} from "@/types/alert"
import type { Competitor } from "@/types/competitor"
import type { MarketOpportunity } from "@/types/dashboard"
import type { Recommendation } from "@/types/recommendation"
import {
  RealtimeEventName,
  type AlertFailedEvent,
  type AlertSentEvent,
  type CompetitorUpdatedEvent,
  type DashboardSummaryUpdatedEvent,
  type MarketOpportunityDetectedEvent,
  type ProductSnapshotSentEvent,
  type RecommendationCreatedEvent,
  type RoomSubscriptionRequest,
  type RealtimeRoomTarget,
  type StockRiskDetectedEvent,
  type UrgencyScoreUpdatedEvent,
} from "@/types/realtime"

type UseLiveDashboardOptions = {
  sellerId?: string
  productIds?: string[]
  rooms?: RoomSubscriptionRequest
  enabled?: boolean
}

const upsertById = <T extends { id: string }>(
  items: T[] | undefined,
  item: T
) => {
  const existing = items ?? []
  const index = existing.findIndex((entry) => entry.id === item.id)
  if (index === -1) {
    return [item, ...existing]
  }
  const updated = [...existing]
  updated[index] = item
  return updated
}

const appendActivity = (
  items: ActivityItem[] | undefined,
  item: ActivityItem
) => {
  const next = [item, ...(items ?? [])]
  return next.slice(0, 12)
}

const buildActivityItem = (
  data: {
    id: string
    title: string
    description: string
    timestamp: string
    category: ActivityItem["category"]
    severity: ActivitySeverity
  }
): ActivityItem => ({
  id: data.id,
  title: data.title,
  description: data.description,
  timestamp: data.timestamp,
  category: data.category,
  severity: data.severity,
})

const mapAlertSeverity = (severity: AlertSeverity): ActivitySeverity =>
  severity === AlertSeverity.Critical
    ? ActivitySeverity.Critical
    : ActivitySeverity.Warning

const useEventDeduper = () => {
  const seenRef = useRef(new Map<string, number>())

  return useCallback((eventId?: string) => {
    if (!eventId) {
      return true
    }
    const now = Date.now()
    const seenAt = seenRef.current.get(eventId)
    if (seenAt) {
      return false
    }
    seenRef.current.set(eventId, now)
    if (seenRef.current.size > 500) {
      for (const [key, value] of seenRef.current.entries()) {
        if (now - value > 5 * 60_000) {
          seenRef.current.delete(key)
        }
      }
    }
    return true
  }, [])
}

const buildDefaultRooms = (
  sellerId?: string,
  productIds?: string[]
): RoomSubscriptionRequest => {
  const rooms: RealtimeRoomTarget[] = [
    { scope: "dashboard" },
    { scope: "alerts" },
    { scope: "activity" },
  ]
  if (sellerId) {
    rooms.push({ scope: "seller", id: sellerId })
  }
  if (productIds?.length) {
    rooms.push(...productIds.map((id) => ({ scope: "product" as const, id })))
  }
  return { rooms }
}

export function useLiveDashboard(options: UseLiveDashboardOptions = {}) {
  const { sellerId, productIds, rooms, enabled = true } = options
  const queryClient = useQueryClient()
  const shouldProcess = useEventDeduper()
  const subscription = useMemo(
    () => rooms ?? buildDefaultRooms(sellerId, productIds),
    [rooms, sellerId, productIds]
  )
  const realtimeStatus = useRealtime({
    rooms: subscription,
    autoConnect: enabled,
  })

  const applyAlert = useCallback(
    (alert: Alert) => {
      queryClient.setQueryData<Alert[]>(
        activeAlertsQueryKey,
        (current) => upsertById(current, alert)
      )
      queryClient.setQueryData<Alert[]>(
        alertHistoryQueryKey,
        (current) => upsertById(current, alert)
      )
      queryClient.setQueryData<AlertSummary | undefined>(
        alertSummaryQueryKey,
        (current) =>
          current
            ? {
                ...current,
                activeCount: current.activeCount + 1,
                criticalCount:
                  alert.severity === AlertSeverity.Critical
                    ? current.criticalCount + 1
                    : current.criticalCount,
                lastTriggeredAt: alert.createdAt,
              }
            : current
      )
    },
    [queryClient]
  )

  const handleRecommendation = useCallback(
    (event: RecommendationCreatedEvent) => {
      if (!shouldProcess(event.eventId)) {
        return
      }
      const recommendation = event.payload.recommendation
      queryClient.setQueryData<Recommendation[]>(
        recommendationsQueryKey,
        (current) => upsertById(current, recommendation)
      )
      queryClient.setQueryData<ActivityItem[]>(
        activityQueryKey,
        (current) =>
          appendActivity(
            current,
            buildActivityItem({
              id: `rec-${recommendation.id}`,
              title: "Recommendation generated",
              description: recommendation.summary,
              timestamp: recommendation.createdAt,
              category: "recommendation",
              severity: ActivitySeverity.Info,
            })
          )
      )
      queryClient.setQueryData<DashboardSummary | undefined>(
        summaryQueryKey,
        (current) =>
          current
            ? {
                ...current,
                aiRecommendations: current.aiRecommendations + 1,
                lastSyncedAt: new Date().toISOString(),
              }
            : current
      )
    },
    [queryClient, shouldProcess]
  )

  const handleAlertSent = useCallback(
    (event: AlertSentEvent) => {
      if (!shouldProcess(event.eventId)) {
        return
      }
      const alert = event.payload.alert
      applyAlert(alert)
      queryClient.setQueryData<ActivityItem[]>(
        activityQueryKey,
        (current) =>
          appendActivity(
            current,
            buildActivityItem({
              id: `alert-${alert.id}`,
              title: alert.title,
              description: alert.message,
              timestamp: alert.createdAt,
              category: "alert",
              severity: mapAlertSeverity(alert.severity),
            })
          )
      )
      queryClient.setQueryData<DashboardSummary | undefined>(
        summaryQueryKey,
        (current) =>
          current
            ? {
                ...current,
                activeAlerts: current.activeAlerts + 1,
                lastSyncedAt: new Date().toISOString(),
              }
            : current
      )
    },
    [applyAlert, queryClient, shouldProcess]
  )

  const handleAlertFailed = useCallback(
    (event: AlertFailedEvent) => {
      if (!shouldProcess(event.eventId)) {
        return
      }
      const message =
        event.payload.reason ?? "Telegram delivery failed for a new alert."
      queryClient.setQueryData<ActivityItem[]>(
        activityQueryKey,
        (current) =>
          appendActivity(
            current,
            buildActivityItem({
              id: `alert-failed-${event.payload.alertId ?? event.eventId}`,
              title: "Alert delivery failed",
              description: message,
              timestamp: event.timestamp,
              category: "system",
              severity: ActivitySeverity.Warning,
            })
          )
      )
    },
    [queryClient, shouldProcess]
  )

  const handleCompetitorUpdated = useCallback(
    (event: CompetitorUpdatedEvent) => {
      if (!shouldProcess(event.eventId)) {
        return
      }
      const competitor = event.payload.competitor
      queryClient.setQueryData<Competitor[]>(
        competitorsQueryKey,
        (current) => upsertById(current, competitor)
      )
      queryClient.setQueryData<ActivityItem[]>(
        activityQueryKey,
        (current) =>
          appendActivity(
            current,
            buildActivityItem({
              id: `comp-${competitor.id}`,
              title: "Competitor update",
              description: `${competitor.competitor} adjusted ${competitor.product}.`,
              timestamp: competitor.lastUpdated,
              category: "competitor",
              severity: ActivitySeverity.Info,
            })
          )
      )
    },
    [queryClient, shouldProcess]
  )

  const handleStockRisk = useCallback(
    (event: StockRiskDetectedEvent) => {
      if (!shouldProcess(event.eventId)) {
        return
      }
      const alert = event.payload.alert
      applyAlert(alert)
      queryClient.setQueryData<ActivityItem[]>(
        activityQueryKey,
        (current) =>
          appendActivity(
            current,
            buildActivityItem({
              id: `risk-${alert.id}`,
              title: "Stock risk detected",
              description: alert.message,
              timestamp: alert.createdAt,
              category: "alert",
              severity: mapAlertSeverity(alert.severity),
            })
          )
      )
    },
    [applyAlert, queryClient, shouldProcess]
  )

  const handleUrgencyScoreUpdated = useCallback(
    (event: UrgencyScoreUpdatedEvent) => {
      if (!shouldProcess(event.eventId)) {
        return
      }
      queryClient.setQueryData<DashboardSummary | undefined>(
        summaryQueryKey,
        (current) =>
          current
            ? {
                ...current,
                urgencyScore: event.payload.urgencyScore,
                lastSyncedAt: event.payload.updatedAt,
              }
            : current
      )
      queryClient.setQueryData<ActivityItem[]>(
        activityQueryKey,
        (current) =>
          appendActivity(
            current,
            buildActivityItem({
              id: `urgency-${event.eventId}`,
              title: "Urgency score updated",
              description: event.payload.reason ?? "Urgency recalculated",
              timestamp: event.payload.updatedAt,
              category: "system",
              severity: ActivitySeverity.Warning,
            })
          )
      )
    },
    [queryClient, shouldProcess]
  )

  const handleSummaryUpdated = useCallback(
    (event: DashboardSummaryUpdatedEvent) => {
      if (!shouldProcess(event.eventId)) {
        return
      }
      queryClient.setQueryData(summaryQueryKey, event.payload.summary)
      queryClient.setQueryData<ActivityItem[]>(
        activityQueryKey,
        (current) =>
          appendActivity(
            current,
            buildActivityItem({
              id: `summary-${event.eventId}`,
              title: "Dashboard summary updated",
              description: "Live metrics refreshed",
              timestamp: event.payload.summary.lastSyncedAt,
              category: "system",
              severity: ActivitySeverity.Info,
            })
          )
      )
    },
    [queryClient, shouldProcess]
  )

  const handleMarketOpportunity = useCallback(
    (event: MarketOpportunityDetectedEvent) => {
      if (!shouldProcess(event.eventId)) {
        return
      }
      const opportunity = event.payload.opportunity
      queryClient.setQueryData<MarketOpportunity[]>(
        marketOpportunitiesQueryKey,
        (current) => upsertById(current, opportunity)
      )
      queryClient.setQueryData<ActivityItem[]>(
        activityQueryKey,
        (current) =>
          appendActivity(
            current,
            buildActivityItem({
              id: `opp-${opportunity.id}`,
              title: "Market opportunity detected",
              description: opportunity.title,
              timestamp: new Date().toISOString(),
              category: "recommendation",
              severity: ActivitySeverity.Info,
            })
          )
      )
      queryClient.setQueryData<DashboardSummary | undefined>(
        summaryQueryKey,
        (current) =>
          current
            ? {
                ...current,
                revenueOpportunities: current.revenueOpportunities + 1,
                lastSyncedAt: new Date().toISOString(),
              }
            : current
      )
    },
    [queryClient, shouldProcess]
  )

  const handleProductSnapshotSent = useCallback(
    (event: ProductSnapshotSentEvent) => {
      if (!shouldProcess(event.eventId)) {
        return
      }
      const title = event.payload.productTitle
        ? `Snapshot sent for ${event.payload.productTitle}`
        : "Product snapshot sent"
      queryClient.setQueryData<ActivityItem[]>(
        activityQueryKey,
        (current) =>
          appendActivity(
            current,
            buildActivityItem({
              id: `snapshot-${event.eventId}`,
              title,
              description: "Telegram product intelligence snapshot delivered.",
              timestamp: event.payload.timestamp ?? event.timestamp,
              category: "system",
              severity: ActivitySeverity.Info,
            })
          )
      )
    },
    [queryClient, shouldProcess]
  )

  useSocketEvent(RealtimeEventName.RecommendationCreated, handleRecommendation, {
    enabled,
  })
  useSocketEvent(RealtimeEventName.AlertSent, handleAlertSent, { enabled })
  useSocketEvent(RealtimeEventName.AlertFailed, handleAlertFailed, { enabled })
  useSocketEvent(RealtimeEventName.CompetitorUpdated, handleCompetitorUpdated, {
    enabled,
  })
  useSocketEvent(RealtimeEventName.StockRiskDetected, handleStockRisk, { enabled })
  useSocketEvent(RealtimeEventName.UrgencyScoreUpdated, handleUrgencyScoreUpdated, {
    enabled,
  })
  useSocketEvent(
    RealtimeEventName.DashboardSummaryUpdated,
    handleSummaryUpdated,
    { enabled }
  )
  useSocketEvent(RealtimeEventName.MarketOpportunityDetected, handleMarketOpportunity, {
    enabled,
  })
  useSocketEvent(RealtimeEventName.ProductSnapshotSent, handleProductSnapshotSent, {
    enabled,
  })

  return realtimeStatus
}
