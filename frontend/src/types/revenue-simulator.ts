import type { z } from "zod"

import type {
  pricingExplanationApiResponseSchema,
  pricingExplanationInputSchema,
  pricingExplanationSchema,
  revenueSimulationApiResponseSchema,
  revenueSimulationInputSchema,
  revenueSimulationResultSchema,
  revenueSimulationRowSchema,
} from "@/schemas/revenue-simulator"

export type RevenueSimulationInput = z.infer<typeof revenueSimulationInputSchema>

export type RevenueSimulationRow = z.infer<typeof revenueSimulationRowSchema>

export type RevenueSimulationResult = z.infer<typeof revenueSimulationResultSchema>

export type RevenueSimulationApiResponse = z.infer<
  typeof revenueSimulationApiResponseSchema
>

export type PricingExplanationInput = z.infer<typeof pricingExplanationInputSchema>

export type PricingExplanation = z.infer<typeof pricingExplanationSchema>

export type PricingExplanationApiResponse = z.infer<
  typeof pricingExplanationApiResponseSchema
>
