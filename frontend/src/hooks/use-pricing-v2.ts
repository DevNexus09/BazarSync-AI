import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  getEffectiveMarketplaceFeePolicy,
  listMarketplaceFeePolicies,
} from "@/services/pricing-policy-service"
import {
  getLatestPricingAnalytics,
  getLatestPricingRecommendation,
  getPricingAnalyticsHistory,
  getPricingOverview,
  getPricingPolicy,
  refreshProductPricing,
  setPricingRecommendationStatus,
} from "@/services/pricing-v2-service"

export const MARKETPLACE = "Daraz Bangladesh"

export const pricingKeys = {
  all: ["pricing-v2"] as const,
  overview: () => [...pricingKeys.all, "overview"] as const,
  product: (productId: string) => [...pricingKeys.all, "product", productId] as const,
  feePolicies: () => [...pricingKeys.all, "fee-policies"] as const,
}

export function usePricingOverview() {
  return useQuery({ queryKey: pricingKeys.overview(), queryFn: getPricingOverview, staleTime: 60_000 })
}

export function useMarketplaceFeePolicies() {
  return useQuery({
    queryKey: pricingKeys.feePolicies(),
    queryFn: () => listMarketplaceFeePolicies({ marketplace: MARKETPLACE }),
    staleTime: 60_000,
  })
}

export function useProductPricing(productId: string) {
  const key = pricingKeys.product(productId)
  const analytics = useQuery({ queryKey: [...key, "analytics"], queryFn: () => getLatestPricingAnalytics(productId) })
  const recommendation = useQuery({
    queryKey: [...key, "recommendation"],
    queryFn: () => getLatestPricingRecommendation(productId),
  })
  const policy = useQuery({ queryKey: [...key, "policy"], queryFn: () => getPricingPolicy(productId) })
  const fees = useQuery({
    queryKey: [...key, "fees"],
    queryFn: () => getEffectiveMarketplaceFeePolicy({ productId, marketplace: MARKETPLACE }),
  })
  const history = useQuery({ queryKey: [...key, "history"], queryFn: () => getPricingAnalyticsHistory(productId) })
  return { analytics, recommendation, policy, fees, history }
}

export function useRefreshProductPricing(productId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => refreshProductPricing(productId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: pricingKeys.all }),
  })
}

export function useRecommendationDecision(productId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "acknowledge" | "dismiss" }) =>
      setPricingRecommendationStatus(id, decision),
    onSuccess: (updated) => {
      queryClient.setQueryData([...pricingKeys.product(productId), "recommendation"], updated)
      void queryClient.invalidateQueries({ queryKey: pricingKeys.overview() })
    },
  })
}
