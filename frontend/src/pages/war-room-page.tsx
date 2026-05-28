import { useMemo } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { ErrorState } from "@/components/common/error-state"
import { DashboardSummaryHeader } from "@/components/dashboard/dashboard-summary-header"
import { UrgencyScoreWidget } from "@/components/dashboard/urgency-score-widget"
import { OpportunityMetricsPanel } from "@/components/dashboard/opportunity-metrics-panel"
import { CompetitorPriceChart } from "@/components/dashboard/competitor-price-chart"
import { MarketTrendWidget } from "@/components/dashboard/market-trend-widget"
import { MarketOpportunityCard } from "@/components/dashboard/market-opportunity-card"
import { RecommendationCard } from "@/components/dashboard/recommendation-card"
import { RealtimeActivityFeed } from "@/components/dashboard/realtime-feed"
import { StockAlertCard } from "@/components/dashboard/stock-alert-card"
import { AlertHistoryPanel } from "@/components/dashboard/alert-history-panel"
import { CompetitorTable } from "@/components/dashboard/competitor-table"
import { Button } from "@/components/ui/button"
import { useAlerts, useResolveAlert } from "@/hooks/useAlerts"
import { useCompetitors } from "@/hooks/useCompetitors"
import { useDashboard } from "@/hooks/useDashboard"
import { useLiveDashboard } from "@/hooks/useLiveDashboard"
import { useAuth } from "@/hooks/use-auth"

export default function WarRoomPage() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const realtimeStatus = useLiveDashboard({ sellerId: user?.id })
  const {
    summary,
    marketTrends,
    opportunityMetrics,
    marketOpportunities,
    recommendations,
    activity,
    competitorPriceTrend,
  } = useDashboard()
  const competitors = useCompetitors()
  const { activeAlerts, alertHistory } = useAlerts()
  const resolveAlert = useResolveAlert()

  const isRefreshing =
    summary.isFetching ||
    marketTrends.isFetching ||
    opportunityMetrics.isFetching ||
    marketOpportunities.isFetching ||
    recommendations.isFetching ||
    activity.isFetching ||
    competitorPriceTrend.isFetching ||
    competitors.isFetching ||
    activeAlerts.isFetching ||
    alertHistory.isFetching

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ["war-room"] })
  }

  const topOpportunities = useMemo(
    () => (marketOpportunities.data ?? []).slice(0, 3),
    [marketOpportunities.data]
  )
  const topRecommendations = useMemo(
    () => (recommendations.data ?? []).slice(0, 2),
    [recommendations.data]
  )
  const recommendationHistory = useMemo(
    () => (recommendations.data ?? []).slice(0, 4),
    [recommendations.data]
  )

  return (
    <div className="space-y-6">
      {summary.isError && !summary.data ? (
        <ErrorState
          title="War Room unavailable"
          message="We couldn't load the War Room summary."
          action={
            <Button variant="outline" size="sm" onClick={() => summary.refetch()}>
              Retry
            </Button>
          }
        />
      ) : (
        <DashboardSummaryHeader
          summary={summary.data}
          isLoading={summary.isLoading}
          isRefreshing={isRefreshing}
          realtimeStatus={realtimeStatus}
          onRefresh={handleRefresh}
        />
      )}

      <div className="grid gap-6 lg:grid-cols-[2.2fr_1fr]">
        <div className="space-y-6">
          <div className="grid gap-4 md:grid-cols-2">
            <UrgencyScoreWidget
              score={summary.data?.urgencyScore}
              isLoading={summary.isLoading}
            />
            {opportunityMetrics.isError ? (
              <ErrorState
                title="Opportunity metrics unavailable"
                message="We couldn't load opportunity metrics."
                action={
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => opportunityMetrics.refetch()}
                  >
                    Retry
                  </Button>
                }
              />
            ) : (
              <OpportunityMetricsPanel
                metrics={opportunityMetrics.data}
                isLoading={opportunityMetrics.isLoading}
              />
            )}
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
            <CompetitorPriceChart
              data={competitorPriceTrend.data}
              isLoading={competitorPriceTrend.isLoading}
              isError={competitorPriceTrend.isError}
              onRetry={() => competitorPriceTrend.refetch()}
            />
            <MarketTrendWidget
              data={marketTrends.data}
              isLoading={marketTrends.isLoading}
              isError={marketTrends.isError}
              onRetry={() => marketTrends.refetch()}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border bg-background p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-foreground">
                  Market opportunities
                </h3>
                <span className="text-xs text-muted-foreground">
                  {marketOpportunities.data?.length ?? 0} total
                </span>
              </div>
              {marketOpportunities.isLoading ? (
                <div className="mt-4 space-y-3">
                  {Array.from({ length: 3 }).map((_, index) => (
                    <div
                      key={`opportunity-skeleton-${index}`}
                      className="h-24 rounded-lg bg-muted/30"
                    />
                  ))}
                </div>
              ) : marketOpportunities.isError ? (
                <div className="mt-4">
                  <ErrorState
                    title="Opportunities unavailable"
                    message="We couldn't load market opportunities."
                    action={
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => marketOpportunities.refetch()}
                      >
                        Retry
                      </Button>
                    }
                  />
                </div>
              ) : topOpportunities.length === 0 ? (
                <div className="mt-4 rounded-lg border border-dashed bg-muted/30 p-4 text-xs text-muted-foreground">
                  No live opportunities detected yet.
                </div>
              ) : (
                <div className="mt-4 space-y-3">
                  {topOpportunities.map((opportunity) => (
                    <MarketOpportunityCard
                      key={opportunity.id}
                      opportunity={opportunity}
                    />
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-xl border bg-background p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-foreground">
                  Priority recommendations
                </h3>
                <span className="text-xs text-muted-foreground">
                  {recommendations.data?.length ?? 0} total
                </span>
              </div>
              {recommendations.isLoading ? (
                <div className="mt-4 space-y-3">
                  {Array.from({ length: 2 }).map((_, index) => (
                    <div
                      key={`recommendation-skeleton-${index}`}
                      className="h-28 rounded-lg bg-muted/30"
                    />
                  ))}
                </div>
              ) : recommendations.isError ? (
                <div className="mt-4">
                  <ErrorState
                    title="Recommendations unavailable"
                    message="We couldn't load AI recommendations."
                    action={
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => recommendations.refetch()}
                      >
                        Retry
                      </Button>
                    }
                  />
                </div>
              ) : topRecommendations.length === 0 ? (
                <div className="mt-4 rounded-lg border border-dashed bg-muted/30 p-4 text-xs text-muted-foreground">
                  AI recommendations will appear as they are generated.
                </div>
              ) : (
                <div className="mt-4 space-y-3">
                  {topRecommendations.map((recommendation) => (
                    <RecommendationCard
                      key={recommendation.id}
                      recommendation={recommendation}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <RealtimeActivityFeed
            items={activity.data}
            isLoading={activity.isLoading}
            isError={activity.isError}
            onRetry={() => activity.refetch()}
          />
          <StockAlertCard
            alerts={activeAlerts.data}
            isLoading={activeAlerts.isLoading}
            isError={activeAlerts.isError}
            onRetry={() => activeAlerts.refetch()}
          />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <div className="space-y-6">
          <AlertHistoryPanel
            alerts={alertHistory.data}
            isLoading={alertHistory.isLoading}
            isError={alertHistory.isError}
            onRetry={() => alertHistory.refetch()}
            onResolve={(alertId) => resolveAlert.mutate(alertId)}
            resolvingId={
              resolveAlert.isPending ? resolveAlert.variables ?? null : null
            }
          />
          <div className="rounded-xl border bg-background p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-foreground">
                Recommendation history
              </h3>
              <span className="text-xs text-muted-foreground">
                {recommendations.data?.length ?? 0} total
              </span>
            </div>
            {recommendations.isLoading ? (
              <div className="mt-4 space-y-3">
                {Array.from({ length: 3 }).map((_, index) => (
                  <div
                    key={`recommendation-history-skeleton-${index}`}
                    className="h-20 rounded-lg bg-muted/30"
                  />
                ))}
              </div>
            ) : recommendations.isError ? (
              <div className="mt-4">
                <ErrorState
                  title="History unavailable"
                  message="We couldn't load recommendation history."
                  action={
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => recommendations.refetch()}
                    >
                      Retry
                    </Button>
                  }
                />
              </div>
            ) : recommendationHistory.length === 0 ? (
              <div className="mt-4 rounded-lg border border-dashed bg-muted/30 p-4 text-xs text-muted-foreground">
                Recommendation history will populate as signals are issued.
              </div>
            ) : (
              <div className="mt-4 space-y-3">
                {recommendationHistory.map((recommendation) => (
                  <RecommendationCard
                    key={recommendation.id}
                    recommendation={recommendation}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
        <CompetitorTable
          competitors={competitors.data}
          isLoading={competitors.isLoading}
          isError={competitors.isError}
          onRetry={() => competitors.refetch()}
        />
      </div>
    </div>
  )
}