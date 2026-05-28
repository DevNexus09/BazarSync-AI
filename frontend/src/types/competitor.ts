export const StockStatus = {
  InStock: "in_stock",
  LowStock: "low_stock",
  OutOfStock: "out_of_stock",
} as const

export type StockStatus = (typeof StockStatus)[keyof typeof StockStatus]

export const CompetitorTrend = {
  Up: "up",
  Down: "down",
  Flat: "flat",
} as const

export type CompetitorTrend =
  (typeof CompetitorTrend)[keyof typeof CompetitorTrend]

export const CompetitorStatus = {
  Active: "active",
  Monitoring: "monitoring",
  Paused: "paused",
} as const

export type CompetitorStatus =
  (typeof CompetitorStatus)[keyof typeof CompetitorStatus]

export type Competitor = {
  id: string
  product: string
  competitor: string
  competitorPrice: number
  sellerPrice: number
  priceGap: number
  stockStatus: StockStatus
  urgencyScore: number
  recommendationAction: string
  trend: CompetitorTrend
  lastUpdated: string
  status: CompetitorStatus
}

export type CompetitorPricePoint = {
  timestamp: string
  competitorPrice: number
  sellerPrice: number
  marketAverage: number
}
