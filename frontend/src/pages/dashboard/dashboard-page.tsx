import { useMemo, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { Lightbulb } from "lucide-react"

import { ErrorState } from "@/components/common/error-state"
import { DashboardSummaryHeader } from "@/components/dashboard/dashboard-summary-header"
import { UrgencyScoreWidget } from "@/components/dashboard/urgency-score-widget"
import { OpportunityMetricsPanel } from "@/components/dashboard/opportunity-metrics-panel"
import { CompetitorPriceChart } from "@/components/dashboard/competitor-price-chart"
import { MarketTrendWidget } from "@/components/dashboard/market-trend-widget"
import { MarketOpportunityCard } from "@/components/dashboard/market-opportunity-card"
import { RealtimeActivityFeed } from "@/components/dashboard/realtime-feed"
import { cn } from "@/lib/utils"
import { StockAlertCard } from "@/components/dashboard/stock-alert-card"
import { CompetitorTable } from "@/components/dashboard/competitor-table"
import { CompetitorHeatmap } from "@/components/dashboard/competitor-heatmap"
import { EmptyHint } from "@/components/dashboard/empty-hint"
import { InventorySnapshotCard } from "@/components/dashboard/inventory-snapshot-card"
import { RecommendationCard } from "@/components/dashboard/recommendation-card"
import { Button } from "@/components/ui/button"
import { UrlTabs } from "@/components/ui/tabs"
import { useAlerts } from "@/hooks/useAlerts"
import { useCompetitors } from "@/hooks/useCompetitors"
import { useDashboard } from "@/hooks/useDashboard"
import { useInventoryIntelligenceSummary } from "@/hooks/useInventoryIntelligence"
import { usePricingOverview } from "@/hooks/use-pricing-v2"
import {
  RecommendationAction,
  type Recommendation,
} from "@/types/recommendation"

// Where the seller acts on each recommendation type.
function recommendationTarget(action: Recommendation["action"]) {
  if (action === RecommendationAction.Restock) {
    return { to: "/app/inventory-intelligence", label: "Open inventory" }
  }
  if (action === RecommendationAction.Bundle) {
    return { to: "/app/recommendations", label: "Open recommendations" }
  }
  return { to: "/app/pricing", label: "Open pricing" }
}

type DashboardSectionProps = {
  id: string
  title: string
  description: string
  action?: ReactNode
  children: ReactNode
  className?: string
}

// One titled group of related widgets; spacing, not boxes, separates groups.
function DashboardSection({
  id,
  title,
  description,
  action,
  children,
  className,
}: DashboardSectionProps) {
  return (
    <section aria-labelledby={id} className={cn("space-y-4", className)}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id={id} className="text-base font-semibold text-foreground">
            {title}
          </h2>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export default function DashboardPage() {
  const queryKey = useDashboard()
  const {
    summary,
    marketTrends,
    opportunityMetrics,
    marketOpportunities,
    recommendations,
    activity,
    competitorPriceTrend,
  } = queryKey
  const competitors = useCompetitors()
  const { activeAlerts } = useAlerts()
  const inventorySummary = useInventoryIntelligenceSummary()
  const pricingOverview = usePricingOverview()

  const isRefreshing =
    summary.isFetching ||
    marketTrends.isFetching ||
    opportunityMetrics.isFetching ||
    marketOpportunities.isFetching ||
    activity.isFetching ||
    competitorPriceTrend.isFetching ||
    recommendations.isFetching ||
    competitors.isFetching ||
    activeAlerts.isFetching

  const topOpportunities = useMemo(
    () => (marketOpportunities.data ?? []).slice(0, 3),
    [marketOpportunities.data]
  )

  const opportunitiesPanel = (
    <div className="grid gap-4 lg:grid-cols-2">
      <OpportunityMetricsPanel
        metrics={opportunityMetrics.data}
        isLoading={opportunityMetrics.isLoading}
        isError={opportunityMetrics.isError}
        onRetry={() => opportunityMetrics.refetch()}
      />
      <div className="glass-panel p-4">
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
                className="h-24 animate-pulse rounded-lg bg-muted/30"
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
          <EmptyHint
            message="No market opportunities yet. They come from recommendations that have competitor evidence."
            actionLabel="Track competitors"
            to="/app/competitors"
          />
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
    </div>
  )

  const insights = summary.data?.insights.slice(0, 2) ?? []

  return (
    <div className="space-y-6">
      {summary.isError && !summary.data ? (
        <ErrorState
          title="AI Operations Center unavailable"
          message="We couldn't load the AI operations dashboard."
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
          onRefresh={() => queryKey.summary.refetch()}
          aside={
            <UrgencyScoreWidget
              score={summary.data?.urgencyScore}
              isLoading={summary.isLoading}
            />
          }
        />
      )}

      {/* Overview charts sit right under the KPIs so they are visible without scrolling. */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-12">
        <div className="min-w-0 xl:col-span-5">
          <MarketTrendWidget
            data={marketTrends.data}
            isLoading={marketTrends.isLoading}
            isError={marketTrends.isError}
            onRetry={() => marketTrends.refetch()}
          />
        </div>
        <div className="min-w-0 xl:col-span-4">
          <CompetitorPriceChart
            data={competitorPriceTrend.data}
            isLoading={competitorPriceTrend.isLoading}
            isError={competitorPriceTrend.isError}
            onRetry={() => competitorPriceTrend.refetch()}
          />
        </div>
        <div className="min-w-0 md:col-span-2 xl:col-span-3">
          <InventorySnapshotCard
            inventory={inventorySummary.data}
            marginAtRisk={pricingOverview.data?.summary.marginAtRisk}
            isLoading={inventorySummary.isLoading}
            isError={inventorySummary.isError}
          />
        </div>
      </div>

      <div className="grid gap-6 pt-4 xl:grid-cols-12">
        <div className="min-w-0 xl:col-span-8">
          <DashboardSection
            id="next-actions"
            className="flex h-full flex-col"
            title="Next actions"
            description="Your most urgent recommendations, with where to act on them."
            action={
              <Button variant="outline" size="xs" asChild>
                <Link to="/app/recommendations">All recommendations</Link>
              </Button>
            }
          >
            {recommendations.isLoading ? (
              <div className="grid gap-3 md:grid-cols-3">
                {Array.from({ length: 3 }).map((_, index) => (
                  <div
                    key={`next-action-skeleton-${index}`}
                    className="h-44 animate-pulse rounded-xl bg-muted/30"
                  />
                ))}
              </div>
            ) : recommendations.isError ? (
              <ErrorState
                title="Next actions unavailable"
                message="We couldn't load your top recommendations."
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
            ) : !recommendations.data?.length ? (
              <EmptyHint
                message="No recommendations yet. Generate one for a product to get your first action."
                actionLabel="Generate recommendations"
                to="/app/recommendations"
              />
            ) : (
              <div className="grid flex-1 gap-3 md:grid-cols-3">
                {recommendations.data.map((recommendation) => {
                  const target = recommendationTarget(recommendation.action)
                  return (
                    <RecommendationCard
                      key={recommendation.id}
                      recommendation={recommendation}
                      action={
                        <Button variant="outline" size="xs" asChild>
                          <Link to={target.to}>{target.label}</Link>
                        </Button>
                      }
                    />
                  )
                })}
              </div>
            )}
          </DashboardSection>
        </div>

        <aside aria-label="Insights and activity" className="space-y-4 xl:col-span-4">
          {insights.length ? (
            <ul className="space-y-2">
              {insights.map((insight) => (
                <li key={insight.id} className="flex gap-2 text-sm">
                  <Lightbulb
                    aria-hidden
                    className="mt-0.5 size-4 shrink-0 text-primary"
                  />
                  <span>
                    <span className="font-semibold text-foreground">
                      {insight.title}.
                    </span>{" "}
                    <span className="text-muted-foreground">
                      {insight.summary}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          <div className="max-h-[28rem] overflow-y-auto rounded-xl">
            <RealtimeActivityFeed
              items={activity.data}
              isLoading={activity.isLoading}
              isError={activity.isError}
              onRetry={() => activity.refetch()}
            />
          </div>
        </aside>
      </div>

      <DashboardSection
        id="details"
        title="Details"
        description="Open one view at a time: opportunities, competitors or stock alerts."
      >
        <UrlTabs
          label="Dashboard details"
          param="view"
          defaultValue="opportunities"
          tabs={[
            {
              value: "opportunities",
              label: `Opportunities (${marketOpportunities.data?.length ?? 0})`,
              content: opportunitiesPanel,
            },
            {
              value: "competitors",
              label: `Competitors (${competitors.data?.length ?? 0})`,
              content: (
                <div className="space-y-4">
                  <CompetitorHeatmap
                    competitors={competitors.data}
                    isLoading={competitors.isLoading}
                    isError={competitors.isError}
                    onRetry={() => competitors.refetch()}
                  />
                  <CompetitorTable
                    competitors={competitors.data}
                    isLoading={competitors.isLoading}
                    isError={competitors.isError}
                    onRetry={() => competitors.refetch()}
                  />
                </div>
              ),
            },
            {
              value: "alerts",
              label: `Stock alerts (${activeAlerts.data?.length ?? 0})`,
              content: (
                <StockAlertCard
                  alerts={activeAlerts.data}
                  isLoading={activeAlerts.isLoading}
                  isError={activeAlerts.isError}
                  onRetry={() => activeAlerts.refetch()}
                />
              ),
            },
          ]}
        />
      </DashboardSection>
    </div>
  )
}
