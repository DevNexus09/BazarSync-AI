import apiClient from "@/api/client"
import {
  AlertCategory,
  AlertChannel,
  AlertSeverity,
  AlertStatus,
} from "@/types/alert"
import type { Alert, AlertSummary } from "@/types/alert"

type PaginationMeta = {
  total: number
  page: number
  page_size: number
  total_pages: number
  has_next: boolean
  has_prev: boolean
}

type PaginatedResponse<T> = {
  items: T[]
  meta: PaginationMeta
}

type ApiAlertRecord = {
  alert_id: string
  product_id: string
  product_title: string
  alert_type: string
  urgency_level: string
  action_type: string
  confidence: string
  delivery_status: string
  delivery_timestamp?: string | null
  telegram_reference?: string | null
  is_read: boolean
  read_at?: string | null
  created_at: string
}

const formatLabel = (value: string | null | undefined) => {
  if (!value) {
    return "alert"
  }
  return value.replace(/_/g, " ").toLowerCase()
}

const mapSeverity = (urgencyLevel: string): AlertSeverity => {
  switch (urgencyLevel?.toUpperCase()) {
    case "CRITICAL":
      return AlertSeverity.Critical
    case "HIGH":
      return AlertSeverity.High
    case "MEDIUM":
      return AlertSeverity.Medium
    default:
      return AlertSeverity.Low
  }
}

const mapStatus = (record: ApiAlertRecord): AlertStatus => {
  if (record.is_read || record.read_at) {
    return AlertStatus.Resolved
  }
  if (record.delivery_status === "delivered") {
    return AlertStatus.Acknowledged
  }
  return AlertStatus.New
}

const mapCategory = (record: ApiAlertRecord): AlertCategory => {
  const actionType = record.action_type?.toUpperCase()
  if (actionType === "STOCK_WARNING" || actionType === "REORDER") {
    return AlertCategory.StockRisk
  }
  if (actionType?.startsWith("PRICE")) {
    return AlertCategory.PriceWar
  }
  if (actionType === "OPPORTUNITY_CAPTURE") {
    return AlertCategory.Opportunity
  }
  if (record.alert_type?.toLowerCase().includes("system")) {
    return AlertCategory.System
  }
  return AlertCategory.CompetitorMove
}

const mapChannel = (record: ApiAlertRecord): AlertChannel => {
  if (record.telegram_reference) {
    return AlertChannel.Telegram
  }
  return AlertChannel.Dashboard
}

const mapUrgencyScore = (urgencyLevel: string) => {
  switch (urgencyLevel?.toUpperCase()) {
    case "CRITICAL":
      return 90
    case "HIGH":
      return 75
    case "MEDIUM":
      return 55
    default:
      return 30
  }
}

const mapAlert = (alert: ApiAlertRecord): Alert => ({
  id: alert.alert_id,
  title: `${formatLabel(alert.action_type).replace(
    /^./,
    (char) => char.toUpperCase()
  )} for ${alert.product_title}`,
  message: `${formatLabel(alert.alert_type)} alert, ${formatLabel(
    alert.urgency_level
  )} urgency.`,
  severity: mapSeverity(alert.urgency_level),
  status: mapStatus(alert),
  category: mapCategory(alert),
  channel: mapChannel(alert),
  product: alert.product_title,
  competitor: null,
  urgencyScore: mapUrgencyScore(alert.urgency_level),
  createdAt: alert.created_at,
})

const fetchAlerts = async (
  params: Record<string, string | number | boolean | undefined>,
  signal?: AbortSignal
) => {
  const { data } = await apiClient.get<PaginatedResponse<ApiAlertRecord>>(
    "/dashboard/alerts",
    {
      signal,
      params,
    }
  )
  return data
}

export async function getActiveAlerts(
  signal?: AbortSignal
): Promise<Alert[]> {
  const data = await fetchAlerts(
    {
      is_read: false,
      sort_by: "created_at",
      sort_direction: "desc",
      page_size: 100,
    },
    signal
  )
  return data.items.map(mapAlert)
}

export async function getAlertHistory(
  signal?: AbortSignal
): Promise<Alert[]> {
  const data = await fetchAlerts(
    {
      sort_by: "created_at",
      sort_direction: "desc",
      page_size: 200,
    },
    signal
  )
  return data.items.map(mapAlert)
}

export async function getAlertSummary(
  signal?: AbortSignal
): Promise<AlertSummary> {
  const [active, critical, latest] = await Promise.all([
    fetchAlerts({ is_read: false, page_size: 1 }, signal),
    fetchAlerts({ urgency_level: "CRITICAL", page_size: 1 }, signal),
    fetchAlerts(
      { sort_by: "created_at", sort_direction: "desc", page_size: 1 },
      signal
    ),
  ])
  return {
    activeCount: active.meta.total,
    criticalCount: critical.meta.total,
    lastTriggeredAt: latest.items[0]?.created_at ?? null,
  }
}

export async function resolveAlert(
  alertId: string
): Promise<{ id: string; status: AlertStatus }> {
  const { data } = await apiClient.patch<{ id: string; status: string }>(
    `/dashboard/alerts/${alertId}/resolve`
  )
  return {
    id: data.id,
    status:
      data.status === "resolved" ? AlertStatus.Resolved : AlertStatus.New,
  }
}