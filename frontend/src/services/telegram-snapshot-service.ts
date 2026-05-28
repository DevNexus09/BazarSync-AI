import apiClient from "@/api/client"
import type { ProductSnapshotSendResponse } from "@/types/product-snapshot"

type ApiProductSnapshotResponse = {
  success: boolean
  message: string
  sent_at?: string | null
  delivery_status?: string | null
}

export async function sendProductSnapshot(
  productId: string
): Promise<ProductSnapshotSendResponse> {
  const { data } = await apiClient.post<ApiProductSnapshotResponse>(
    "/telegram/send-product-snapshot",
    {
      product_id: productId,
    },
    {
      timeout: 30000,
    }
  )
  return {
    success: data.success,
    message: data.message,
    sentAt: data.sent_at ?? null,
    deliveryStatus: data.delivery_status ?? null,
  }
}
