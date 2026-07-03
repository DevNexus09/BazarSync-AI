import { useMutation } from "@tanstack/react-query"

import {
  explainRevenueSimulation,
  simulateRevenue,
} from "@/services/pricing-simulator-service"
import type { RevenueSimulationRequest } from "@/types/pricing-simulator"

export function usePricingSimulator(productId: string | null) {
  const simulateMutation = useMutation({
    mutationFn: (payload: RevenueSimulationRequest) => {
      if (!productId) {
        throw new Error("Select a product first.")
      }
      return simulateRevenue(productId, payload)
    },
  })

  const explainMutation = useMutation({
    mutationFn: (payload: RevenueSimulationRequest) => {
      if (!productId) {
        throw new Error("Select a product first.")
      }
      return explainRevenueSimulation(productId, payload)
    },
  })

  return {
    simulation: explainMutation.data?.simulation ?? simulateMutation.data,
    explanation: explainMutation.data ?? null,
    simulate: simulateMutation.mutate,
    explain: explainMutation.mutate,
    isSimulating: simulateMutation.isPending,
    isExplaining: explainMutation.isPending,
    simulationError: simulateMutation.error,
    explanationError: explainMutation.error,
    reset: () => {
      simulateMutation.reset()
      explainMutation.reset()
    },
  }
}
