import { z } from "zod"

const moneySchema = z.number().finite()
const MAX_PRICE = 1_000_000_000
const MAX_TOTAL = 1_000_000_000_000_000

export const revenueSimulationRowSchema = z.object({
  price: moneySchema.positive().max(MAX_PRICE),
  estimatedUnits: z.number().int().nonnegative().max(MAX_PRICE),
  revenue: moneySchema.max(MAX_TOTAL),
  profit: moneySchema.min(-MAX_TOTAL).max(MAX_TOTAL),
  margin: moneySchema.min(-1_000_000).max(1_000_000),
  warning: z.string().optional(),
})

export const revenueSimulationInputSchema = z.object({
  productId: z.string().max(120).optional(),
  productName: z.string().trim().min(1, "Product Name is required.").max(120),
  candidatePrices: z
    .array(
      moneySchema
        .positive("Candidate prices must be greater than 0.")
        .max(MAX_PRICE, "Candidate prices are too large.")
    )
    .min(1, "At least one candidate price is required.")
    .max(20, "You can test up to 20 candidate prices at once."),
  unitCost: moneySchema
    .nonnegative("Unit Cost cannot be negative.")
    .max(MAX_PRICE, "Unit Cost is too large."),
  baselinePrice: moneySchema
    .positive("Baseline Price must be greater than 0.")
    .max(MAX_PRICE, "Baseline Price is too large."),
  baselineMonthlyUnits: moneySchema
    .positive("Baseline Monthly Units must be greater than 0.")
    .max(MAX_PRICE, "Baseline Monthly Units is too large."),
  priceElasticity: moneySchema.max(0).optional(),
})

export const revenueSimulationResultSchema = z.object({
  simulations: z.array(revenueSimulationRowSchema).min(1),
  recommendedPrice: moneySchema.positive(),
  recommendedSimulation: revenueSimulationRowSchema,
  baseline: z.object({
    price: moneySchema.positive(),
    estimatedUnits: z.number().int().nonnegative().max(MAX_PRICE),
    revenue: moneySchema.max(MAX_TOTAL),
    profit: moneySchema.min(-MAX_TOTAL).max(MAX_TOTAL),
    margin: moneySchema.min(-1_000_000).max(1_000_000),
  }),
  expectedRevenueImpact: z.string(),
  expectedProfitImpact: z.string(),
})

export const revenueSimulationApiResponseSchema = z.object({
  success: z.literal(true),
  data: revenueSimulationResultSchema,
})

export const pricingExplanationInputSchema = z.object({
  productName: z.string().trim().min(1).max(120),
  baselinePrice: moneySchema.positive().max(MAX_PRICE),
  recommendedPrice: moneySchema.positive().max(MAX_PRICE),
  expectedRevenueImpact: z.string().min(1).max(32),
  expectedProfitImpact: z.string().min(1).max(32),
  simulations: z.array(revenueSimulationRowSchema).min(1).max(20),
})

export const pricingExplanationSchema = z.object({
  banglaReasoning: z.string().min(1),
  businessExplanation: z.string().min(1),
  expectedImpact: z.string().min(1),
})

export const pricingExplanationApiResponseSchema = z.object({
  success: z.literal(true),
  data: pricingExplanationSchema,
})
