export const CompetitorEventType = {
  PriceDrop: "PRICE_DROP",
  PriceRise: "PRICE_RISE",
  OutOfStock: "OUT_OF_STOCK",
  BackInStock: "BACK_IN_STOCK",
  NewCompetitor: "NEW_COMPETITOR",
  CompetitorRemoved: "COMPETITOR_REMOVED",
} as const

export type CompetitorEventType =
  (typeof CompetitorEventType)[keyof typeof CompetitorEventType]

export const EventSeverity = {
  Low: "LOW",
  Medium: "MEDIUM",
  High: "HIGH",
  Critical: "CRITICAL",
} as const

export type EventSeverity = (typeof EventSeverity)[keyof typeof EventSeverity]

export const OpportunityLevel = {
  Low: "LOW",
  Medium: "MEDIUM",
  High: "HIGH",
} as const

export type OpportunityLevel =
  (typeof OpportunityLevel)[keyof typeof OpportunityLevel]

export type Phase5DashboardFilters = {
  productId?: string
  windowHours: number
  eventType?: CompetitorEventType | "ALL"
  severity?: EventSeverity | "ALL"
  opportunityLevel?: OpportunityLevel | "ALL"
}

export type Phase5Summary = {
  competitorCount: number
  priceDropCount: number
  stockoutCount: number
  openOpportunityCount: number
  lastUpdatedAt: string | null
  windowHours: number
  windowStart: string
  windowEnd: string
  competitorCountScope: string
  eventCountScope: string
  opportunityCountScope: string
}

export type LatestPriceChange = {
  id: string
  competitorId: string
  competitor: string | null
  productId: string
  product: string | null
  oldPrice: number | null
  newPrice: number | null
  changeAmount: number | null
  changePercentage: number | null
  eventType: Extract<
    CompetitorEventType,
    typeof CompetitorEventType.PriceDrop | typeof CompetitorEventType.PriceRise
  >
  eventTime: string
  severity: EventSeverity
}

export type CompetitorActivity = {
  id: string
  eventType: CompetitorEventType
  competitorId: string
  competitor: string | null
  productId: string
  product: string | null
  description: string
  severity: EventSeverity
  eventTime: string
  supportingValues: {
    old?: Record<string, unknown> | null
    new?: Record<string, unknown> | null
  } | null
}

export type OpportunityFeedItem = {
  id: string
  opportunityLevel: OpportunityLevel
  opportunityScore: number
  estimatedRevenue: number | null
  estimatedRevenueState: "estimated" | "insufficient_data"
  recommendedAction: string
  confidenceScore: number
  explanation: string
  evidenceSummary: string
  status: string
  detectedAt: string
}

export type MarketPositionCard = {
  sellerProductPrice: number | null
  lowestCompetitorPrice: number | null
  medianCompetitorPrice: number | null
  highestCompetitorPrice: number | null
  strongestCompetitorId: string | null
  sellerPriceDifferenceFromMarketMedian: number | null
  totalActiveCompetitors: number
  totalInStockCompetitors: number
  rankingLastUpdatedAt: string | null
  sellerPriceRank: number | null
}

export type TopCompetitor = {
  id: string
  competitorId: string
  competitor: string | null
  competitorStore: string | null
  productId: string
  product: string | null
  marketRank: number
  totalScore: number
  priceScore: number
  ratingScore: number
  reviewScore: number
  availabilityScore: number
  price: number | null
  rating: number | null
  reviewCount: number | null
  stockStatus: string | null
  sourceUrl: string | null
  calculatedAt: string
}

export type PageResponse<T> = {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type Phase5RealtimeEventName =
  | "competitor.snapshot.created"
  | "competitor.event.created"
  | "competitor.rankings.updated"
  | "market.opportunity.created"
  | "competitor.summary.updated"

export type Phase5RealtimeEnvelope = {
  version: 1
  event: Phase5RealtimeEventName
  seller_id: string
  product_id: string
  occurred_at: string
  data: Record<string, unknown>
}
