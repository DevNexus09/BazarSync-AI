import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  getInventoryIntelligenceSummary,
  getInventoryReorderList,
  getInventoryRisks,
  getProductInventoryIntelligence,
  runDailyInventoryWorkflow,
  runProductInventoryWorkflow,
} from "@/services/inventory-intelligence-service"
import type { InventoryRiskLevel } from "@/types/inventory-intelligence"

type InventoryListFilters = {
  productId?: string
  riskLevel?: InventoryRiskLevel | "ALL"
  insufficientData?: boolean
  sort?: "deadline" | "risk" | "recommended_quantity"
  limit?: number
  offset?: number
}

export const inventoryIntelligenceKeys = {
  all: ["inventory-intelligence"] as const,
  summary: () => [...inventoryIntelligenceKeys.all, "summary"] as const,
  reorderList: (filters: InventoryListFilters) =>
    [...inventoryIntelligenceKeys.all, "reorder-list", filters] as const,
  risks: (filters: InventoryListFilters) =>
    [...inventoryIntelligenceKeys.all, "risks", filters] as const,
  product: (productId?: string) =>
    [...inventoryIntelligenceKeys.all, "product", productId || "none"] as const,
}

export function useInventoryIntelligenceSummary() {
  return useQuery({
    queryKey: inventoryIntelligenceKeys.summary(),
    queryFn: ({ signal }) => getInventoryIntelligenceSummary(signal),
    refetchInterval: 30_000,
  })
}

export function useInventoryReorderList(filters: InventoryListFilters) {
  return useQuery({
    queryKey: inventoryIntelligenceKeys.reorderList(filters),
    queryFn: ({ signal }) => getInventoryReorderList({ ...filters, signal }),
    refetchInterval: 30_000,
  })
}

export function useInventoryRisks(filters: InventoryListFilters) {
  return useQuery({
    queryKey: inventoryIntelligenceKeys.risks(filters),
    queryFn: ({ signal }) => getInventoryRisks({ ...filters, signal }),
    refetchInterval: 30_000,
  })
}

export function useProductInventoryIntelligence(productId?: string) {
  return useQuery({
    queryKey: inventoryIntelligenceKeys.product(productId),
    queryFn: ({ signal }) => {
      if (!productId) {
        return Promise.reject(new Error("Product id is required"))
      }
      return getProductInventoryIntelligence(productId, signal)
    },
    enabled: Boolean(productId),
    refetchInterval: 30_000,
  })
}

export function useRunDailyInventoryWorkflow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: runDailyInventoryWorkflow,
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: inventoryIntelligenceKeys.all,
      }),
  })
}

export function useRunProductInventoryWorkflow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: runProductInventoryWorkflow,
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: inventoryIntelligenceKeys.all,
      }),
  })
}
