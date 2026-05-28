import { useMutation } from "@tanstack/react-query"

import { useProducts } from "@/hooks/use-products"
import { sendProductSnapshot } from "@/services/telegram-snapshot-service"

export function useProductSnapshot() {
  const productsQuery = useProducts()
  const sendSnapshot = useMutation({
    mutationFn: (productId: string) => sendProductSnapshot(productId),
  })

  return {
    productsQuery,
    sendSnapshot,
  }
}
