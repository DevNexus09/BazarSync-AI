import apiClient from "@/api/client"
import type {
  CompetitorActivity,
  CompetitorEventType,
  EventSeverity,
  LatestPriceChange,
  MarketPositionCard,
  OpportunityFeedItem,
  OpportunityLevel,
  PageResponse,
  Phase5Summary,
  TopCompetitor,
} from "@/types/phase5-dashboard"

type PriceChangeType = "PRICE_DROP" | "PRICE_RISE"

type FeedPage<T> = {
  items: T[]
  total: number
  limit: number
  offset: number
}

type ApiSummary = {
  competitor_count: number
  price_drop_count: number
  stockout_count: number
  open_opportunity_count: number
  last_updated_at?: string | null
  window_hours: number
  window_start: string
  window_end: string
  competitor_count_scope: string
  event_count_scope: string
  opportunity_count_scope: string
}

type ApiPriceChange = {
  competitor_id: string
  competitor?: string | null
  product_id: string
  product?: string | null
  old_price?: number | string | null
  new_price?: number | string | null
  change_amount?: number | string | null
  change_percentage?: number | string | null
  event_type?: CompetitorEventType
  event_time: string
  severity: EventSeverity
}

type ApiActivity = {
  event_type: CompetitorEventType
  competitor_id: string
  competitor?: string | null
  product_id: string
  product?: string | null
  description: string
  severity: EventSeverity
  event_time: string
  supporting_values?: {
    old?: Record<string, unknown> | null
    new?: Record<string, unknown> | null
  } | null
}

type ApiOpportunity = {
  id: string
  opportunity_level: OpportunityLevel
  opportunity_score: number | string
  estimated_revenue?: number | string | null
  estimated_revenue_state?: "estimated" | "insufficient_data"
  recommended_action: string
  confidence_score: number | string
  explanation: string
  evidence?: Record<string, unknown> | null
  status: string
  detected_at: string
}

type ApiMarketPositionCard = {
  seller_product_price?: number | string | null
  lowest_competitor_price?: number | string | null
  median_competitor_price?: number | string | null
  highest_competitor_price?: number | string | null
  strongest_competitor_id?: string | null
  seller_price_difference_from_market_median?: number | string | null
  total_active_competitors: number
  total_in_stock_competitors: number
  ranking_last_updated_at?: string | null
  seller_price_rank?: number | null
}

type ApiTopCompetitor = {
  id: string
  competitor_id: string
  competitor?: string | null
  competitor_store?: string | null
  product_id: string
  product?: string | null
  market_rank: number
  total_score: number | string
  price_score: number | string
  rating_score: number | string
  review_score: number | string
  availability_score: number | string
  price?: number | string | null
  rating?: number | string | null
  review_count?: number | null
  stock_status?: string | null
  source_url?: string | null
  calculated_at: string
}

type ListParams = {
  productId?: string
  windowHours?: number
  limit?: number
  offset?: number
  opportunityLevel?: OpportunityLevel | "ALL"
  signal?: AbortSignal
}

const toNumberOrNull = (value?: number | string | null) => {
  if (value == null || value === "") {
    return null
  }
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue : null
}

const toNumber = (value: number | string) => Number(value)

const page = <T>(data: FeedPage<T>): PageResponse<T> => ({
  items: data.items,
  total: data.total,
  limit: data.limit,
  offset: data.offset,
})

const evidenceSummary = (evidence?: Record<string, unknown> | null) => {
  if (!evidence || Object.keys(evidence).length === 0) {
    return "No supporting evidence attached."
  }
  return Object.entries(evidence)
    .slice(0, 3)
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${String(value)}`)
    .join("; ")
}

const priceChangeType = (item: ApiPriceChange): PriceChangeType => {
  if (item.event_type === "PRICE_DROP" || item.event_type === "PRICE_RISE") {
    return item.event_type
  }
  const oldPrice = toNumberOrNull(item.old_price)
  const newPrice = toNumberOrNull(item.new_price)
  return oldPrice != null && newPrice != null && newPrice < oldPrice
    ? "PRICE_DROP"
    : "PRICE_RISE"
}

const dashboardParams = ({
  productId,
  windowHours,
  limit,
  offset,
}: ListParams) => ({
  product_id: productId,
  window_hours: windowHours,
  limit,
  offset,
})

export async function getPhase5Summary({
  productId,
  windowHours,
  signal,
}: ListParams): Promise<Phase5Summary> {
  const { data } = await apiClient.get<ApiSummary>("/competitor-dashboard/summary", {
    params: dashboardParams({ productId, windowHours }),
    signal,
  })
  return {
    competitorCount: data.competitor_count,
    priceDropCount: data.price_drop_count,
    stockoutCount: data.stockout_count,
    openOpportunityCount: data.open_opportunity_count,
    lastUpdatedAt: data.last_updated_at ?? null,
    windowHours: data.window_hours,
    windowStart: data.window_start,
    windowEnd: data.window_end,
    competitorCountScope: data.competitor_count_scope,
    eventCountScope: data.event_count_scope,
    opportunityCountScope: data.opportunity_count_scope,
  }
}

export async function getLatestPriceChanges(
  params: ListParams
): Promise<PageResponse<LatestPriceChange>> {
  const { data } = await apiClient.get<FeedPage<ApiPriceChange>>(
    "/competitor-dashboard/latest-price-changes",
    {
      params: dashboardParams(params),
      signal: params.signal,
    }
  )
  return page({
    ...data,
    items: data.items.map((item, index) => ({
      id: `${item.product_id}:${item.competitor_id}:${item.event_time}:${index}`,
      competitorId: item.competitor_id,
      competitor: item.competitor ?? null,
      productId: item.product_id,
      product: item.product ?? null,
      oldPrice: toNumberOrNull(item.old_price),
      newPrice: toNumberOrNull(item.new_price),
      changeAmount: toNumberOrNull(item.change_amount),
      changePercentage: toNumberOrNull(item.change_percentage),
      eventType: priceChangeType(item),
      eventTime: item.event_time,
      severity: item.severity,
    })),
  })
}

export async function getCompetitorActivity(
  params: ListParams
): Promise<PageResponse<CompetitorActivity>> {
  const { data } = await apiClient.get<FeedPage<ApiActivity>>(
    "/competitor-dashboard/activity-feed",
    {
      params: dashboardParams(params),
      signal: params.signal,
    }
  )
  return page({
    ...data,
    items: data.items.map((item, index) => ({
      id: `${item.event_type}:${item.product_id}:${item.competitor_id}:${item.event_time}:${index}`,
      eventType: item.event_type,
      competitorId: item.competitor_id,
      competitor: item.competitor ?? null,
      productId: item.product_id,
      product: item.product ?? null,
      description: item.description,
      severity: item.severity,
      eventTime: item.event_time,
      supportingValues: item.supporting_values ?? null,
    })),
  })
}

export async function getOpportunityFeed(
  params: ListParams
): Promise<PageResponse<OpportunityFeedItem>> {
  const { data } = await apiClient.get<FeedPage<ApiOpportunity>>(
    "/market-opportunities",
    {
      params: {
        product_id: params.productId,
        level:
          params.opportunityLevel && params.opportunityLevel !== "ALL"
            ? params.opportunityLevel
            : undefined,
        status: "OPEN",
        limit: params.limit,
        offset: params.offset,
      },
      signal: params.signal,
    }
  )
  return page({
    ...data,
    items: data.items.map((item) => ({
      id: item.id,
      opportunityLevel: item.opportunity_level,
      opportunityScore: toNumber(item.opportunity_score),
      estimatedRevenue: toNumberOrNull(item.estimated_revenue),
      estimatedRevenueState:
        item.estimated_revenue_state ??
        (item.estimated_revenue == null ? "insufficient_data" : "estimated"),
      recommendedAction: item.recommended_action,
      confidenceScore: toNumber(item.confidence_score),
      explanation: item.explanation,
      evidenceSummary: evidenceSummary(item.evidence),
      status: item.status,
      detectedAt: item.detected_at,
    })),
  })
}

export async function getMarketPositionCard(
  productId: string,
  signal?: AbortSignal
): Promise<MarketPositionCard> {
  const { data } = await apiClient.get<ApiMarketPositionCard>(
    `/competitor-dashboard/products/${productId}/market-position-card`,
    { signal }
  )
  return {
    sellerProductPrice: toNumberOrNull(data.seller_product_price),
    lowestCompetitorPrice: toNumberOrNull(data.lowest_competitor_price),
    medianCompetitorPrice: toNumberOrNull(data.median_competitor_price),
    highestCompetitorPrice: toNumberOrNull(data.highest_competitor_price),
    strongestCompetitorId: data.strongest_competitor_id ?? null,
    sellerPriceDifferenceFromMarketMedian: toNumberOrNull(
      data.seller_price_difference_from_market_median
    ),
    totalActiveCompetitors: data.total_active_competitors,
    totalInStockCompetitors: data.total_in_stock_competitors,
    rankingLastUpdatedAt: data.ranking_last_updated_at ?? null,
    sellerPriceRank: data.seller_price_rank ?? null,
  }
}

export async function getTopCompetitors({
  productId,
  limit,
  signal,
}: ListParams): Promise<PageResponse<TopCompetitor>> {
  const { data } = await apiClient.get<FeedPage<ApiTopCompetitor>>(
    "/competitor-dashboard/top-competitors",
    {
      params: {
        product_id: productId,
        limit,
      },
      signal,
    }
  )
  return page({
    ...data,
    items: data.items.map((item) => ({
      id: item.id,
      competitorId: item.competitor_id,
      competitor: item.competitor ?? null,
      competitorStore: item.competitor_store ?? null,
      productId: item.product_id,
      product: item.product ?? null,
      marketRank: item.market_rank,
      totalScore: toNumber(item.total_score),
      priceScore: toNumber(item.price_score),
      ratingScore: toNumber(item.rating_score),
      reviewScore: toNumber(item.review_score),
      availabilityScore: toNumber(item.availability_score),
      price: toNumberOrNull(item.price),
      rating: toNumberOrNull(item.rating),
      reviewCount: item.review_count ?? null,
      stockStatus: item.stock_status ?? null,
      sourceUrl: item.source_url ?? null,
      calculatedAt: item.calculated_at,
    })),
  })
}

export async function acknowledgeOpportunity(
  opportunityId: string
): Promise<void> {
  await apiClient.post(`/market-opportunities/${opportunityId}/acknowledge`)
}

export async function dismissOpportunity(opportunityId: string): Promise<void> {
  await apiClient.post(`/market-opportunities/${opportunityId}/dismiss`)
}
