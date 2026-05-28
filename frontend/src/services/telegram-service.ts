import apiClient from "@/api/client"
import type {
  PaginationMeta,
  TelegramAlertHistoryResponse,
  TelegramAlertRecord,
  TelegramConnectToken,
  TelegramConnectionStatus,
  TelegramHealth,
  TelegramTestAlertResult,
} from "@/types/telegram"

type ApiTelegramConnectToken = {
  token: string
  expires_at: string
  bot_username?: string | null
}

type ApiTelegramConnectionStatus = {
  is_connected: boolean
  connected_at?: string | null
  telegram_username?: string | null
  telegram_first_name?: string | null
  telegram_last_name?: string | null
  last_alert_sent_at?: string | null
  bot_username?: string | null
}

type ApiTelegramHealth = {
  status: string
  bot_username?: string | null
  bot_id?: number | null
}

type ApiTelegramDisconnectResponse = {
  status: string
}

type ApiPaginationMeta = {
  total: number
  page: number
  page_size: number
  total_pages: number
  has_next: boolean
  has_prev: boolean
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

type ApiAlertHistoryResponse = {
  items: ApiAlertRecord[]
  meta: ApiPaginationMeta
}

type ApiTelegramTestAlertResponse = {
  success: boolean
  status: string
  detail?: string | null
}

const mapConnectToken = (data: ApiTelegramConnectToken): TelegramConnectToken => ({
  token: data.token,
  expiresAt: data.expires_at,
  botUsername: data.bot_username ?? null,
})

const mapStatus = (
  data: ApiTelegramConnectionStatus
): TelegramConnectionStatus => ({
  isConnected: data.is_connected,
  connectedAt: data.connected_at ?? null,
  telegramUsername: data.telegram_username ?? null,
  telegramFirstName: data.telegram_first_name ?? null,
  telegramLastName: data.telegram_last_name ?? null,
  lastAlertSentAt: data.last_alert_sent_at ?? null,
  botUsername: data.bot_username ?? null,
})

const mapHealth = (data: ApiTelegramHealth): TelegramHealth => ({
  status: data.status,
  botUsername: data.bot_username ?? null,
  botId: data.bot_id ?? null,
})

const formatLabel = (value: string | null | undefined) => {
  if (!value) {
    return "alert"
  }
  return value.replace(/_/g, " ").toLowerCase()
}

const mapAlertRecord = (record: ApiAlertRecord): TelegramAlertRecord => ({
  id: record.alert_id,
  alertType: formatLabel(record.alert_type),
  product: record.product_title,
  action: formatLabel(record.action_type),
  sentAt: record.delivery_timestamp ?? record.created_at,
  deliveryStatus: record.delivery_status,
  isTelegram: Boolean(record.telegram_reference),
})

const mapPaginationMeta = (meta: ApiPaginationMeta): PaginationMeta => ({
  total: meta.total,
  page: meta.page,
  pageSize: meta.page_size,
  totalPages: meta.total_pages,
  hasNext: meta.has_next,
  hasPrev: meta.has_prev,
})

export async function getTelegramStatus(
  signal?: AbortSignal
): Promise<TelegramConnectionStatus> {
  const { data } = await apiClient.get<ApiTelegramConnectionStatus>(
    "/telegram/status",
    { signal }
  )
  return mapStatus(data)
}

export async function createTelegramConnectToken(): Promise<TelegramConnectToken> {
  const { data } = await apiClient.post<ApiTelegramConnectToken>(
    "/telegram/connect-token"
  )
  return mapConnectToken(data)
}

export async function disconnectTelegram(): Promise<ApiTelegramDisconnectResponse> {
  const { data } = await apiClient.post<ApiTelegramDisconnectResponse>(
    "/telegram/disconnect"
  )
  return data
}

export async function getTelegramHealth(
  signal?: AbortSignal
): Promise<TelegramHealth> {
  const { data } = await apiClient.get<ApiTelegramHealth>("/telegram/health", {
    signal,
  })
  return mapHealth(data)
}

export async function getTelegramAlertHistory(
  {
    page,
    pageSize,
  }: {
    page: number
    pageSize: number
  },
  signal?: AbortSignal
): Promise<TelegramAlertHistoryResponse> {
  const { data } = await apiClient.get<ApiAlertHistoryResponse>("/dashboard/alerts", {
    signal,
    params: {
      sort_by: "created_at",
      sort_direction: "desc",
      page,
      page_size: pageSize,
    },
  })
  return {
    items: data.items.map(mapAlertRecord),
    meta: mapPaginationMeta(data.meta),
  }
}

export async function sendTelegramTestAlert(
  customMessage?: string
): Promise<TelegramTestAlertResult> {
  const { data } = await apiClient.post<ApiTelegramTestAlertResponse>("/alerts/test", {
    custom_message:
      customMessage ?? "BazarSync AI Telegram alert test for your account.",
  })
  return {
    success: data.success,
    status: data.status,
    detail: data.detail ?? null,
  }
}
