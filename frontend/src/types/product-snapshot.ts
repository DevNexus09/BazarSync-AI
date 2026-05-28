export type ProductSnapshotSendResponse = {
  success: boolean
  message: string
  sentAt?: string | null
  deliveryStatus?: string | null
}

export type ProductSnapshotErrorResponse = {
  success: boolean
  detail: string
  errorCode?: string | null
}
