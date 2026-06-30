import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  acknowledgeOpportunity,
  dismissOpportunity,
  getCompetitorActivity,
  getLatestPriceChanges,
  getMarketPositionCard,
  getOpportunityFeed,
  getPhase5Summary,
  getTopCompetitors,
} from "@/services/phase5-dashboard-service"
import type { Phase5DashboardFilters } from "@/types/phase5-dashboard"

export const phase5DashboardQueryKey = ["phase5-dashboard"] as const
const dashboardRecoveryRefetchMs = 30_000

export const phase5SummaryQueryKey = (filters: Phase5DashboardFilters) =>
  [...phase5DashboardQueryKey, "summary", filters.productId ?? "all", filters.windowHours] as const

export const phase5PriceChangesQueryKey = (
  filters: Phase5DashboardFilters,
  page: { limit: number; offset: number }
) =>
  [
    ...phase5DashboardQueryKey,
    "price-changes",
    filters.productId ?? "all",
    filters.windowHours,
    page.limit,
    page.offset,
  ] as const

export const phase5ActivityQueryKey = (
  filters: Phase5DashboardFilters,
  page: { limit: number; offset: number }
) =>
  [
    ...phase5DashboardQueryKey,
    "activity",
    filters.productId ?? "all",
    filters.windowHours,
    filters.eventType ?? "ALL",
    filters.severity ?? "ALL",
    page.limit,
    page.offset,
  ] as const

export const phase5OpportunityQueryKey = (
  filters: Phase5DashboardFilters,
  page: { limit: number; offset: number }
) =>
  [
    ...phase5DashboardQueryKey,
    "opportunities",
    filters.productId ?? "all",
    filters.opportunityLevel ?? "ALL",
    page.limit,
    page.offset,
  ] as const

export const phase5MarketPositionQueryKey = (productId?: string) =>
  [...phase5DashboardQueryKey, "market-position", productId ?? "none"] as const

export const phase5TopCompetitorsQueryKey = (filters: Phase5DashboardFilters) =>
  [...phase5DashboardQueryKey, "top-competitors", filters.productId ?? "all"] as const

export function usePhase5Dashboard(
  filters: Phase5DashboardFilters,
  page: { limit: number; offset: number }
) {
  const summary = usePhase5Summary(filters)
  const priceChanges = usePhase5PriceChanges(filters, page)
  const activity = usePhase5Activity(filters, page)
  const opportunities = usePhase5Opportunities(filters, page)
  const marketPosition = usePhase5MarketPosition(filters.productId)
  const topCompetitors = usePhase5TopCompetitors(filters)

  return {
    summary,
    priceChanges,
    activity,
    opportunities,
    marketPosition,
    topCompetitors,
  }
}

export function usePhase5Summary(filters: Phase5DashboardFilters) {
  return useQuery({
    queryKey: phase5SummaryQueryKey(filters),
    queryFn: ({ signal }) =>
      getPhase5Summary({
        productId: filters.productId,
        windowHours: filters.windowHours,
        signal,
      }),
    staleTime: 20_000,
    refetchInterval: dashboardRecoveryRefetchMs,
    retry: 2,
  })
}

export function usePhase5PriceChanges(
  filters: Phase5DashboardFilters,
  page: { limit: number; offset: number }
) {
  return useQuery({
    queryKey: phase5PriceChangesQueryKey(filters, page),
    queryFn: ({ signal }) =>
      getLatestPriceChanges({
        productId: filters.productId,
        windowHours: filters.windowHours,
        limit: page.limit,
        offset: page.offset,
        signal,
      }),
    staleTime: 15_000,
    refetchInterval: dashboardRecoveryRefetchMs,
    retry: 2,
  })
}

export function usePhase5Activity(
  filters: Phase5DashboardFilters,
  page: { limit: number; offset: number }
) {
  return useQuery({
    queryKey: phase5ActivityQueryKey(filters, page),
    queryFn: async ({ signal }) => {
      const response = await getCompetitorActivity({
        productId: filters.productId,
        windowHours: filters.windowHours,
        limit: page.limit,
        offset: page.offset,
        signal,
      })
      return {
        ...response,
        items: response.items.filter((item) => {
          const eventMatches =
            !filters.eventType ||
            filters.eventType === "ALL" ||
            item.eventType === filters.eventType
          const severityMatches =
            !filters.severity ||
            filters.severity === "ALL" ||
            item.severity === filters.severity
          return eventMatches && severityMatches
        }),
      }
    },
    staleTime: 10_000,
    refetchInterval: dashboardRecoveryRefetchMs,
    retry: 2,
  })
}

export function usePhase5Opportunities(
  filters: Phase5DashboardFilters,
  page: { limit: number; offset: number }
) {
  return useQuery({
    queryKey: phase5OpportunityQueryKey(filters, page),
    queryFn: ({ signal }) =>
      getOpportunityFeed({
        productId: filters.productId,
        opportunityLevel: filters.opportunityLevel,
        limit: page.limit,
        offset: page.offset,
        signal,
      }),
    staleTime: 20_000,
    refetchInterval: dashboardRecoveryRefetchMs,
    retry: 2,
  })
}

export function usePhase5MarketPosition(productId?: string) {
  return useQuery({
    queryKey: phase5MarketPositionQueryKey(productId),
    queryFn: ({ signal }) => {
      if (!productId) {
        return Promise.reject(new Error("Select a product to view market position."))
      }
      return getMarketPositionCard(productId, signal)
    },
    enabled: Boolean(productId),
    staleTime: 30_000,
    refetchInterval: productId ? dashboardRecoveryRefetchMs : false,
    retry: 2,
  })
}

export function usePhase5TopCompetitors(filters: Phase5DashboardFilters) {
  return useQuery({
    queryKey: phase5TopCompetitorsQueryKey(filters),
    queryFn: ({ signal }) =>
      getTopCompetitors({
        productId: filters.productId,
        limit: 10,
        signal,
      }),
    staleTime: 30_000,
    refetchInterval: dashboardRecoveryRefetchMs,
    retry: 2,
  })
}

export function useOpportunityActions() {
  const queryClient = useQueryClient()
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: phase5DashboardQueryKey })

  const acknowledge = useMutation({
    mutationFn: acknowledgeOpportunity,
    onSuccess: invalidate,
  })

  const dismiss = useMutation({
    mutationFn: dismissOpportunity,
    onSuccess: invalidate,
  })

  return { acknowledge, dismiss }
}
