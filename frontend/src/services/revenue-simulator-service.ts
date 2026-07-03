import apiClient from "@/api/client"
import {
  pricingExplanationApiResponseSchema,
  pricingExplanationInputSchema,
  revenueSimulationApiResponseSchema,
  revenueSimulationInputSchema,
} from "@/schemas/revenue-simulator"
import type {
  PricingExplanation,
  PricingExplanationApiResponse,
  PricingExplanationInput,
  RevenueSimulationApiResponse,
  RevenueSimulationInput,
  RevenueSimulationResult,
} from "@/types/revenue-simulator"
import { env } from "@/utils/env"

export async function simulateRevenue(
  input: RevenueSimulationInput
): Promise<RevenueSimulationResult> {
  const payload = revenueSimulationInputSchema.parse(input)
  const response = await apiClient.post<RevenueSimulationApiResponse>(
    publicPricingUrl("/simulate"),
    payload
  )
  return revenueSimulationApiResponseSchema.parse(response.data).data
}

export async function generatePricingExplanation(
  input: PricingExplanationInput
): Promise<PricingExplanation> {
  const payload = pricingExplanationInputSchema.parse(input)
  const response = await apiClient.post<PricingExplanationApiResponse>(
    publicPricingUrl("/explain"),
    payload
  )
  return pricingExplanationApiResponseSchema.parse(response.data).data
}

function publicPricingUrl(path: "/simulate" | "/explain") {
  return `${backendRootUrl()}/api/pricing${path}`
}

function backendRootUrl() {
  return env.apiBaseUrl.replace(/\/api\/v1\/?$/, "").replace(/\/$/, "")
}
