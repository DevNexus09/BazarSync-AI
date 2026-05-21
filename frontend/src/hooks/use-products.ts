import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  createProduct,
  deleteProduct,
  getProduct,
  getProducts,
  updateProduct,
} from "@/services/product-service"
import type { ProductInput } from "@/types/product"

const productsQueryKey = ["products"]
const productQueryKey = (productId: string) => ["products", productId]

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

export function useProduct(productId?: string) {
  return useQuery({
    queryKey: productId ? productQueryKey(productId) : ["products", "unknown"],
    queryFn: () => {
      if (!productId) {
        return Promise.reject(new Error("Product id is required"))
      }
      return getProduct(productId)
    },
    enabled: Boolean(productId),
    staleTime: 30_000,
  })
}

export function useUpdateProduct() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload: { productId: string; input: ProductInput }) =>
      updateProduct(payload.productId, payload.input),
    onSuccess: (product, payload) => {
      queryClient.invalidateQueries({ queryKey: productsQueryKey })
      queryClient.setQueryData(productQueryKey(payload.productId), product)
    },
  })
}

export function useDeleteProduct() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (productId: string) => deleteProduct(productId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: productsQueryKey,
      }),
  })
}
