import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  getDeadStockProducts,
  getDeadStockSummary,
  getProductDeadStockIntelligence,
  simulateCapitalRecovery,
} from "@/services/dead-stock-service"
import {
  getDeadStockReadiness,
  recalculateDeadStock,
} from "@/services/dead-stock-readiness-service"
import type { DeadStockFilters, RecoverySimulationInput } from "@/types/dead-stock"

export const deadStockKeys = {
  all: ["dead-stock"] as const,
  summary: () => [...deadStockKeys.all, "summary"] as const,
  products: (filters: DeadStockFilters) =>
    [...deadStockKeys.all, "products", filters] as const,
  product: (productId?: string) =>
    [...deadStockKeys.all, "product", productId || "none"] as const,
  readiness: (productId?: string) =>
    [...deadStockKeys.all, "readiness", productId || "none"] as const,
}

export function useDeadStockSummary() {
  return useQuery({
    queryKey: deadStockKeys.summary(),
    queryFn: ({ signal }) => getDeadStockSummary(signal),
    refetchInterval: 30_000,
  })
}

export function useDeadStockProducts(filters: DeadStockFilters) {
  return useQuery({
    queryKey: deadStockKeys.products(filters),
    queryFn: ({ signal }) => getDeadStockProducts({ ...filters, signal }),
    refetchInterval: 30_000,
  })
}

export function useProductDeadStockIntelligence(productId?: string) {
  return useQuery({
    queryKey: deadStockKeys.product(productId),
    queryFn: ({ signal }) => {
      if (!productId) return Promise.reject(new Error("Product id is required"))
      return getProductDeadStockIntelligence(productId, signal)
    },
    enabled: Boolean(productId),
    refetchInterval: 30_000,
  })
}

export function useDeadStockReadiness(productId?: string) {
  return useQuery({
    queryKey: deadStockKeys.readiness(productId),
    queryFn: ({ signal }) => {
      if (!productId) return Promise.reject(new Error("Product id is required"))
      return getDeadStockReadiness(productId, signal)
    },
    enabled: Boolean(productId),
    refetchInterval: 30_000,
  })
}

export function useDeadStockRecalculation(productId?: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => {
      if (!productId) return Promise.reject(new Error("Product id is required"))
      return recalculateDeadStock(productId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: deadStockKeys.summary() })
      queryClient.invalidateQueries({ queryKey: deadStockKeys.product(productId) })
      queryClient.invalidateQueries({ queryKey: deadStockKeys.readiness(productId) })
      queryClient.invalidateQueries({ queryKey: deadStockKeys.all })
    },
  })
}

export function useRecoverySimulation(productId?: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: RecoverySimulationInput) => {
      if (!productId) return Promise.reject(new Error("Product id is required"))
      return simulateCapitalRecovery(productId, input)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: deadStockKeys.product(productId) })
    },
  })
}
