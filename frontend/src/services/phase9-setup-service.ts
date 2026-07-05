import apiClient from "@/api/client"

export type InventoryStockInInput = {
  productId: string
  quantity: number
  receivedAt: string
  unitCost?: number | null
  currency?: string | null
  sourceReference?: string | null
  notes?: string | null
}

export type SalesImportInput = {
  productId: string
  quantity: number
  soldAt: string
  status: "PENDING" | "COMPLETED" | "FULFILLED" | "CANCELLED" | "FAILED_PAYMENT"
  unitPrice?: number | null
  currency?: string | null
  sourceReference: string
  isTestOrder: boolean
}

export type PricingPolicySetupInput = {
  productId: string
  marketplace: string
  currency: string
  minimumMarginPercent: number
  minimumUnitProfit: number
  maximumDiscountPercent: number
  maximumPriceIncreasePercent: number
  minimumAllowedPrice?: number | null
  maximumAllowedPrice?: number | null
  priceIncrement: number
  objective: string
  effectiveFrom: string
}

export type VisibilityMetricInput = {
  productId: string
  marketplace: string
  metricDate: string
  impressions: number
  views: number
  clicks: number
  searchRank?: number | null
  listingQualityScore?: number | null
  conversionRate?: number | null
  source: string
}

export async function createInventoryStockIn(input: InventoryStockInInput) {
  const { data } = await apiClient.post("/inventory/stock-in", {
    product_id: input.productId,
    quantity: input.quantity,
    received_at: input.receivedAt,
    unit_cost: input.unitCost ?? null,
    currency: input.currency || null,
    source_reference: input.sourceReference || null,
    notes: input.notes || null,
  })
  return data
}

export async function importSalesRecord(input: SalesImportInput) {
  const { data } = await apiClient.post("/sales/import", {
    records: [
      {
        product_id: input.productId,
        quantity: input.quantity,
        sold_at: input.soldAt,
        status: input.status,
        unit_price: input.unitPrice ?? null,
        currency: input.currency || null,
        source_reference: input.sourceReference,
        is_test_order: input.isTestOrder,
      },
    ],
  })
  return data
}

export async function createPricingPolicy(input: PricingPolicySetupInput) {
  const { data } = await apiClient.post("/pricing-policies", {
    product_id: input.productId,
    marketplace: input.marketplace,
    currency: input.currency,
    minimum_margin_rate: percentToRate(input.minimumMarginPercent),
    minimum_unit_profit: input.minimumUnitProfit,
    maximum_price_decrease_rate: percentToRate(input.maximumDiscountPercent),
    maximum_price_increase_rate: percentToRate(input.maximumPriceIncreasePercent),
    minimum_allowed_price: input.minimumAllowedPrice ?? null,
    maximum_allowed_price: input.maximumAllowedPrice ?? null,
    price_increment: input.priceIncrement,
    objective: input.objective,
    is_active: true,
    effective_from: input.effectiveFrom,
  })
  return data
}

export async function createVisibilityMetric(input: VisibilityMetricInput) {
  const { data } = await apiClient.post(
    `/products/${input.productId}/visibility-metrics`,
    {
      marketplace: input.marketplace,
      metric_date: input.metricDate,
      impressions: input.impressions,
      views: input.views,
      clicks: input.clicks,
      search_rank: input.searchRank ?? null,
      listing_quality_score: input.listingQualityScore ?? null,
      conversion_rate: input.conversionRate ?? null,
      source: input.source,
    }
  )
  return data
}

export function percentToRate(value: number) {
  return Number((value / 100).toFixed(6))
}
