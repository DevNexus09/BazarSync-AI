import { z } from "zod"

const number = z.union([z.number(), z.string().trim().min(1)])
  .transform(Number)
  .pipe(z.number().finite())
const units = number.pipe(z.number().nonnegative())
const dateTime = z.iso.datetime({ offset: true })
const reasons = z.array(z.string()).default([])

export const dashboardEvidenceSchema = z.object({
  competitor_observed_at: dateTime.nullish(),
  competitor_freshness: z.enum(["FRESH", "PARTIAL", "STALE", "UNKNOWN", "UNAVAILABLE"]).nullish(),
  inventory_observed_at: dateTime.nullish(),
  sales_through: z.iso.date().nullish(),
  available_units: units.nullish(),
  daily_sales_rate: units.nullish(),
  sales_rate_observed: z.boolean().nullish(),
  target_price: units.nullish(),
  reason_codes: reasons,
  insufficient_evidence: z.boolean().default(false),
  price_blocked: z.boolean().default(false),
  forecasts: z.array(z.object({
    horizon_days: z.literal([7, 14, 30]),
    expected_units: units,
    method: z.string(),
    version: z.string(),
    source: z.enum(["active", "previous"]),
    data_cutoff: dateTime,
    uncertainty: z.string(),
    prediction_interval: z.tuple([units, units]).nullish(),
  })).default([]),
  supporting_actions: z.array(z.object({ action: z.string(), source: z.string() })).default([]),
  pricing_candidates: z.array(z.object({
    price: number,
    constraints_passed: z.boolean(),
    price_change_eligible: z.boolean().nullish(),
    rejection_reasons: reasons,
  })).default([]),
  reorder: z.object({
    quantity: units.nullish(),
    deadline: z.iso.date().nullish(),
    reorder_point: units.nullish(),
    lead_time_demand: units.nullish(),
    validated_demand_upper_bound: units.nullish(),
    demand_source: z.enum(["approved_forecast", "recorded_sales_velocity"]).nullish(),
    uncertainty: z.string().nullish(),
  }).nullish(),
})

export type DashboardEvidence = z.infer<typeof dashboardEvidenceSchema>
