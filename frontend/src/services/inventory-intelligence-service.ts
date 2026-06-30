import apiClient from "@/api/client"
import type {
  InventoryIntelligenceItem,
  InventoryIntelligencePage,
  InventoryIntelligenceSummary,
  InventoryRiskLevel,
  InventoryWorkflowResponse,
  ProductInventoryIntelligence,
} from "@/types/inventory-intelligence"

type ApiSummary = {
  total_active_products: number
  low_risk_products: number
  medium_risk_products: number
  high_risk_products: number
  critical_risk_products: number
  insufficient_data_products: number
  products_requiring_reorder: number
  products_already_out_of_stock: number
  last_calculation_time?: string | null
  data_freshness_status: string
}

type ApiListItem = {
  product_id: string
  product_name: string
  category?: string | null
  risk_level?: InventoryRiskLevel | null
  risk_score?: number | string | null
  data_status?: string | null
  days_remaining?: number | string | null
  predicted_stockout_date?: string | null
  reorder_action?: string | null
  recommendation_status?: string | null
  recommended_quantity?: number | null
  reorder_deadline?: string | null
  calculation_version?: string | null
  as_of_date?: string | null
  last_updated_at?: string | null
}

type ApiPage = {
  items: ApiListItem[]
  total: number
  limit: number
  offset: number
}

type ApiProductIntelligence = {
  product_id: string
  product_name: string
  category?: string | null
  latest_inventory_snapshot_id?: string | null
  inventory_snapshot_date?: string | null
  quantity_on_hand?: number | null
  quantity_reserved?: number | null
  quantity_available?: number | null
  quantity_incoming?: number | null
  daily_sales_rate?: number | string | null
  velocity_window_days?: number | null
  velocity_data_status?: string | null
  days_remaining?: number | string | null
  predicted_stockout_date?: string | null
  stockout_prediction_status?: string | null
  supplier_lead_time_days?: number | null
  safety_buffer_days?: number | null
  inventory_risk_score?: number | string | null
  risk_level?: InventoryRiskLevel | null
  reorder_action?: string | null
  recommended_quantity?: number | null
  reorder_deadline?: string | null
  confidence_score?: number | string | null
  data_status?: string | null
  explanation?: string | null
  calculation_version?: string | null
  as_of_date?: string | null
  last_updated_at?: string | null
  metadata?: Record<string, unknown> | null
}

type ApiWorkflow = {
  workflow_id: string
  scope: string
  seller_id?: string | null
  product_id?: string | null
  as_of_date?: string | null
}

type ListParams = {
  productId?: string
  riskLevel?: InventoryRiskLevel | "ALL"
  insufficientData?: boolean
  sort?: "deadline" | "risk" | "recommended_quantity"
  limit?: number
  offset?: number
  signal?: AbortSignal
}

const toNumberOrNull = (value?: number | string | null) => {
  if (value == null || value === "") {
    return null
  }
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

const listParams = (params: ListParams) => ({
  product_id: params.productId || undefined,
  risk_level:
    params.riskLevel && params.riskLevel !== "ALL" ? params.riskLevel : undefined,
  insufficient_data: params.insufficientData,
  sort: params.sort,
  limit: params.limit,
  offset: params.offset,
})

const mapSummary = (data: ApiSummary): InventoryIntelligenceSummary => ({
  totalActiveProducts: data.total_active_products,
  lowRiskProducts: data.low_risk_products,
  mediumRiskProducts: data.medium_risk_products,
  highRiskProducts: data.high_risk_products,
  criticalRiskProducts: data.critical_risk_products,
  insufficientDataProducts: data.insufficient_data_products,
  productsRequiringReorder: data.products_requiring_reorder,
  productsAlreadyOutOfStock: data.products_already_out_of_stock,
  lastCalculationTime: data.last_calculation_time ?? null,
  dataFreshnessStatus: data.data_freshness_status,
})

const mapItem = (item: ApiListItem): InventoryIntelligenceItem => ({
  productId: item.product_id,
  productName: item.product_name,
  category: item.category ?? null,
  riskLevel: item.risk_level ?? null,
  riskScore: toNumberOrNull(item.risk_score),
  dataStatus: item.data_status ?? null,
  daysRemaining: toNumberOrNull(item.days_remaining),
  predictedStockoutDate: item.predicted_stockout_date ?? null,
  reorderAction: item.reorder_action ?? null,
  recommendationStatus: item.recommendation_status ?? null,
  recommendedQuantity: item.recommended_quantity ?? null,
  reorderDeadline: item.reorder_deadline ?? null,
  calculationVersion: item.calculation_version ?? null,
  asOfDate: item.as_of_date ?? null,
  lastUpdatedAt: item.last_updated_at ?? null,
})

const mapPage = (data: ApiPage): InventoryIntelligencePage => ({
  items: data.items.map(mapItem),
  total: data.total,
  limit: data.limit,
  offset: data.offset,
})

const mapProduct = (data: ApiProductIntelligence): ProductInventoryIntelligence => ({
  productId: data.product_id,
  productName: data.product_name,
  category: data.category ?? null,
  latestInventorySnapshotId: data.latest_inventory_snapshot_id ?? null,
  inventorySnapshotDate: data.inventory_snapshot_date ?? null,
  quantityOnHand: data.quantity_on_hand ?? null,
  quantityReserved: data.quantity_reserved ?? null,
  quantityAvailable: data.quantity_available ?? null,
  quantityIncoming: data.quantity_incoming ?? null,
  dailySalesRate: toNumberOrNull(data.daily_sales_rate),
  velocityWindowDays: data.velocity_window_days ?? null,
  velocityDataStatus: data.velocity_data_status ?? null,
  daysRemaining: toNumberOrNull(data.days_remaining),
  predictedStockoutDate: data.predicted_stockout_date ?? null,
  stockoutPredictionStatus: data.stockout_prediction_status ?? null,
  supplierLeadTimeDays: data.supplier_lead_time_days ?? null,
  safetyBufferDays: data.safety_buffer_days ?? null,
  inventoryRiskScore: toNumberOrNull(data.inventory_risk_score),
  riskLevel: data.risk_level ?? null,
  reorderAction: data.reorder_action ?? null,
  recommendedQuantity: data.recommended_quantity ?? null,
  reorderDeadline: data.reorder_deadline ?? null,
  confidenceScore: toNumberOrNull(data.confidence_score),
  dataStatus: data.data_status ?? null,
  explanation: data.explanation ?? null,
  calculationVersion: data.calculation_version ?? null,
  asOfDate: data.as_of_date ?? null,
  lastUpdatedAt: data.last_updated_at ?? null,
  metadata: data.metadata ?? null,
})

const mapWorkflow = (data: ApiWorkflow): InventoryWorkflowResponse => ({
  workflowId: data.workflow_id,
  scope: data.scope,
  sellerId: data.seller_id ?? null,
  productId: data.product_id ?? null,
  asOfDate: data.as_of_date ?? null,
})

export async function getInventoryIntelligenceSummary(signal?: AbortSignal) {
  const { data } = await apiClient.get<ApiSummary>(
    "/inventory-intelligence/summary",
    { signal }
  )
  return mapSummary(data)
}

export async function getInventoryReorderList(params: ListParams) {
  const { data } = await apiClient.get<ApiPage>(
    "/inventory-intelligence/reorder-list",
    {
      params: listParams(params),
      signal: params.signal,
    }
  )
  return mapPage(data)
}

export async function getInventoryRisks(params: ListParams) {
  const { data } = await apiClient.get<ApiPage>("/inventory-intelligence/risks", {
    params: listParams(params),
    signal: params.signal,
  })
  return mapPage(data)
}

export async function getProductInventoryIntelligence(
  productId: string,
  signal?: AbortSignal
) {
  const { data } = await apiClient.get<ApiProductIntelligence>(
    `/inventory-intelligence/products/${productId}`,
    { signal }
  )
  return mapProduct(data)
}

export async function runDailyInventoryWorkflow() {
  const { data } = await apiClient.post<ApiWorkflow>(
    "/inventory-intelligence/workflow/daily"
  )
  return mapWorkflow(data)
}

export async function runProductInventoryWorkflow(productId: string) {
  const { data } = await apiClient.post<ApiWorkflow>(
    `/inventory-intelligence/products/${productId}/workflow`
  )
  return mapWorkflow(data)
}
