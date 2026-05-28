export const RecommendationAction = {
  RaisePrice: "raise_price",
  MatchPrice: "match_price",
  Undercut: "undercut",
  Bundle: "bundle",
  Restock: "restock",
  Hold: "hold",
} as const

export type RecommendationAction =
  (typeof RecommendationAction)[keyof typeof RecommendationAction]

export const RecommendationStatus = {
  New: "new",
  Reviewed: "reviewed",
  Implemented: "implemented",
  Dismissed: "dismissed",
} as const

export type RecommendationStatus =
  (typeof RecommendationStatus)[keyof typeof RecommendationStatus]

export const RecommendationPriority = {
  Low: "low",
  Medium: "medium",
  High: "high",
  Critical: "critical",
} as const

export type RecommendationPriority =
  (typeof RecommendationPriority)[keyof typeof RecommendationPriority]

export type Recommendation = {
  id: string
  title: string
  summary: string
  action: RecommendationAction
  status: RecommendationStatus
  priority: RecommendationPriority
  confidence: number
  expectedLift: number
  product: string
  competitor?: string | null
  createdAt: string
}