import { useQuery } from "@tanstack/react-query"

import {
  getActivityFeed,
  getCompetitorPriceTrend,
  getDashboardSummary,
  getMarketOpportunities,
  getMarketTrends,
  getOpportunityMetrics,
  getRecommendations,
} from "@/services/dashboard-service"

export const summaryQueryKey = ["war-room", "summary"]
export const marketTrendQueryKey = ["war-room", "market-trends"]
export const opportunityMetricsQueryKey = ["war-room", "opportunity-metrics"]
export const marketOpportunitiesQueryKey = ["war-room", "opportunities"]
export const recommendationsQueryKey = ["war-room", "recommendations"]
export const activityQueryKey = ["war-room", "activity"]
export const competitorPriceTrendQueryKey = ["war-room", "competitor-price-trend"]

export function useDashboard() {
  const summary = useQuery({
    queryKey: summaryQueryKey,
    queryFn: ({ signal }) => getDashboardSummary(signal),
    staleTime: 20_000,
    retry: 2,
  })

  const marketTrends = useQuery({
    queryKey: marketTrendQueryKey,
    queryFn: ({ signal }) => getMarketTrends(signal),
    staleTime: 30_000,
    retry: 2,
  })

  const opportunityMetrics = useQuery({
    queryKey: opportunityMetricsQueryKey,
    queryFn: ({ signal }) => getOpportunityMetrics(signal),
    staleTime: 30_000,
    retry: 2,
  })

  const marketOpportunities = useQuery({
    queryKey: marketOpportunitiesQueryKey,
    queryFn: ({ signal }) => getMarketOpportunities(signal),
    staleTime: 30_000,
    retry: 2,
  })

  const recommendations = useQuery({
    queryKey: recommendationsQueryKey,
    queryFn: ({ signal }) => getRecommendations(signal),
    staleTime: 20_000,
    retry: 2,
  })

  const activity = useQuery({
    queryKey: activityQueryKey,
    queryFn: ({ signal }) => getActivityFeed(signal),
    staleTime: 10_000,
    retry: 2,
  })

  const competitorPriceTrend = useQuery({
    queryKey: competitorPriceTrendQueryKey,
    queryFn: ({ signal }) => getCompetitorPriceTrend(signal),
    staleTime: 30_000,
    retry: 2,
  })

  return {
    summary,
    marketTrends,
    opportunityMetrics,
    marketOpportunities,
    recommendations,
    activity,
    competitorPriceTrend,
  }
}