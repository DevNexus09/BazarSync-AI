import apiClient from "@/api/client"

import type {
  ApiCompetitor,
  Competitor,
  CompetitorApiResponse,
  ScrapeRunStatusResponse,
  ScraperRunResponse,
} from "../types/competitor.types"

const toNullableNumber = (
  value: number | string | null | undefined
): number | null => {
  if (value === null || value === undefined) {
    return null
  }
  const parsed = typeof value === "number" ? value : Number(value)
  return Number.isNaN(parsed) ? null : parsed
}

const normalizeCompetitorResponse = (
  payload: CompetitorApiResponse
): ApiCompetitor[] => {
  if (Array.isArray(payload)) {
    return payload
  }

  if ("items" in payload && Array.isArray(payload.items)) {
    return payload.items
  }

  if ("competitors" in payload && Array.isArray(payload.competitors)) {
    return payload.competitors
  }

  if ("data" in payload && Array.isArray(payload.data)) {
    return payload.data
  }

  throw new Error("Unexpected competitor response format.")
}

const mapCompetitor = (competitor: ApiCompetitor): Competitor => ({
  id: String(competitor.id),
  title: competitor.competitor_title?.trim() || "Unknown competitor",
  description: competitor.competitor_description ?? null,
  category: competitor.competitor_category ?? null,
  brand: competitor.competitor_brand ?? null,
  attributes: competitor.competitor_attributes ?? {},
  price: toNullableNumber(competitor.competitor_price),
  rating: toNullableNumber(competitor.competitor_rating),
  soldCount: competitor.competitor_sold ?? null,
  stockStatus: competitor.stock_status?.trim() || "unknown",
  similarityScore: toNullableNumber(competitor.similarity_score),
  titleSimilarity: toNullableNumber(competitor.title_similarity),
  descriptionSimilarity: toNullableNumber(competitor.description_similarity),
  attributeSimilarity: toNullableNumber(competitor.attribute_similarity),
  keywordScore: toNullableNumber(competitor.keyword_score),
  rankingScore: toNullableNumber(competitor.ranking_score),
  matchConfidence: toNullableNumber(competitor.match_confidence),
  categoryMatch:
    typeof competitor.category_match === "boolean"
      ? competitor.category_match
      : null,
  matchedAttributes: competitor.matched_attributes ?? [],
  storeName: competitor.competitor_store?.trim() || "Unknown store",
  productUrl: competitor.product_url ?? null,
  marketplacePosition: competitor.marketplace_position ?? null,
})

export async function getCompetitors(productId: string): Promise<Competitor[]> {
  if (!productId) {
    throw new Error("Product id is required to fetch competitors.")
  }

  const { data } = await apiClient.get<CompetitorApiResponse>(
    `/competitors/${encodeURIComponent(productId)}`
  )
  const items = normalizeCompetitorResponse(data)
  return items.map(mapCompetitor)
}

export async function runScraper(productId: string): Promise<ScraperRunResponse> {
  if (!productId) {
    throw new Error("Product id is required to run the scraper.")
  }

  const { data } = await apiClient.post<ScraperRunResponse>(
    `/scraper/run/${encodeURIComponent(productId)}`
  )
  return data
}

export async function getScrapeRunStatus(
  scrapeRunId: string
): Promise<ScrapeRunStatusResponse> {
  if (!scrapeRunId) {
    throw new Error("Scrape run id is required to fetch status.")
  }

  const { data } = await apiClient.get<ScrapeRunStatusResponse>(
    `/scraper/runs/${encodeURIComponent(scrapeRunId)}`
  )
  return data
}
