import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { createProduct, getProducts } from "@/services/product-service"
import type { ProductInput } from "@/types/product"

const productsQueryKey = ["products"]

export function useProducts() {
  return useQuery({
    queryKey: productsQueryKey,
    queryFn: getProducts,
    staleTime: 30_000,
  })
}

export function useCreateProduct() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: ProductInput) => createProduct(input),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: productsQueryKey,
      }),
  })
}
