import apiClient from "@/api/client"

export type OutcomeType = "PRICING" | "REORDER"
export type ConfidenceBand = "LOW" | "MEDIUM" | "HIGH"
type Summary = { outcomes: number; hitRate: number | null; reliable: boolean }

export type TrackRecord = {
  enabled: boolean
  days: number
  minOutcomes: number
  overall: Summary
  bands: Record<ConfidenceBand, Summary>
}

type ApiSummary = { outcomes: number; hit_rate: number | null; reliable: boolean }
const mapSummary = (item?: ApiSummary): Summary => ({
  outcomes: item?.outcomes ?? 0,
  hitRate: item?.hit_rate ?? null,
  reliable: Boolean(item?.reliable),
})

export async function getTrackRecord(type: OutcomeType): Promise<TrackRecord> {
  const { data } = await apiClient.get("/recommendation-outcomes/track-record", { params: { recommendation_type: type } })
  return {
    enabled: Boolean(data.enabled),
    days: data.days ?? 0,
    minOutcomes: data.min_outcomes ?? 0,
    overall: mapSummary(data),
    bands: {
      LOW: mapSummary(data.bands?.LOW),
      MEDIUM: mapSummary(data.bands?.MEDIUM),
      HIGH: mapSummary(data.bands?.HIGH),
    },
  }
}

/** Same thresholds as the backend bands and the confidence labels: <40 low, <70 medium, otherwise high. */
export function confidenceBand(score: number): ConfidenceBand {
  return score >= 70 ? "HIGH" : score >= 40 ? "MEDIUM" : "LOW"
}
