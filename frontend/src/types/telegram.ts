export type TelegramConnectToken = {
  token: string
  expiresAt: string
  botUsername?: string | null
}

export type TelegramConnectionStatus = {
  isConnected: boolean
  connectedAt?: string | null
  telegramUsername?: string | null
  telegramFirstName?: string | null
  telegramLastName?: string | null
  lastAlertSentAt?: string | null
  botUsername?: string | null
}

export type TelegramHealth = {
  status: string
  botUsername?: string | null
  botId?: number | null
}

export type TelegramConnectionState =
  | "not_connected"
  | "connecting"
  | "connected"
  | "error"

export type TelegramAlertRecord = {
  id: string
  alertType: string
  product: string
  action: string
  sentAt: string
  deliveryStatus: string
  isTelegram: boolean
}

export type PaginationMeta = {
  total: number
  page: number
  pageSize: number
  totalPages: number
  hasNext: boolean
  hasPrev: boolean
}

export type TelegramAlertHistoryResponse = {
  items: TelegramAlertRecord[]
  meta: PaginationMeta
}

export type TelegramTestAlertResult = {
  success: boolean
  status: string
  detail?: string | null
}
