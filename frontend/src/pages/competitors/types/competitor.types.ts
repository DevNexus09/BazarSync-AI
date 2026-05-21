export type ApiCompetitor = {
  id: string | number
  competitor_title: string
  competitor_description?: string | null
  competitor_category?: string | null
  competitor_brand?: string | null
  competitor_attributes?: Record<string, string> | null
  competitor_price: number | string | null
  competitor_rating: number | string | null
  competitor_sold: number | string | null
  stock_status: string | null
  similarity_score: number | string | null
  title_similarity?: number | string | null
  description_similarity?: number | string | null
  attribute_similarity?: number | string | null
  keyword_score?: number | string | null
  ranking_score?: number | string | null
  match_confidence?: number | string | null
  category_match?: boolean | null
  matched_attributes?: string[] | null
  competitor_store: string | null
  product_url?: string | null
  marketplace_position?: number | string | null
}

export type Competitor = {
  id: string
  title: string
  description?: string | null
  category?: string | null
  brand?: string | null
  attributes?: Record<string, string>
  price: number | null
  rating: number | null
  soldCount: number | string | null
  stockStatus: string
  similarityScore: number | null
  titleSimilarity?: number | null
  descriptionSimilarity?: number | null
  attributeSimilarity?: number | null
  keywordScore?: number | null
  rankingScore?: number | null
  matchConfidence?: number | null
  categoryMatch?: boolean | null
  matchedAttributes?: string[]
  storeName: string
  productUrl?: string | null
  marketplacePosition?: number | string | null
}

export type CompetitorListResponse = {
  items: ApiCompetitor[]
  total?: number
  limit?: number
  offset?: number
}

export type CompetitorApiResponse =
  | ApiCompetitor[]
  | CompetitorListResponse
  | {
      competitors: ApiCompetitor[]
      total?: number
      limit?: number
      offset?: number
    }
  | {
      data: ApiCompetitor[]
      total?: number
      limit?: number
      offset?: number
    }

export type ScraperRunResponse = {
  message: string
  status?: string
  run_id?: string
  triggered_at?: string
}
