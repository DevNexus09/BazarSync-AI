import { formatDateTime } from "@/utils/formatters"

import type { DashboardEvidence } from "../types/dashboardEvidence"
import {
  formatRecommendationPrice,
  formatNullableNumber,
} from "../utils/recommendationHelpers"

const horizons = [7, 14, 30] as const

const reasonLabels: Record<string, string> = {
  INSUFFICIENT_SALES_HISTORY: "Sales history is missing or too limited.",
  SALES_HISTORY_UNAVAILABLE: "Sales history is missing or too limited.",
  STALE_COMPETITOR_DATA: "Competitor data was stale when this recommendation was generated.",
  COMPETITOR_PRICE_UNAVAILABLE: "No verified competitor price was available.",
  INVENTORY_UNAVAILABLE: "Verified inventory was unavailable.",
  NO_SUPPORTED_ACTION: "The evidence did not support a change.",
  PRICE_RESPONSE_UNVALIDATED: "The effect of a price change on sales is unknown.",
  BELOW_MINIMUM_MARGIN: "Below the minimum margin.",
  BELOW_MINIMUM_PRICE: "Below the price floor.",
  ABOVE_MAXIMUM_PRICE: "Above the price ceiling.",
  BELOW_MINIMUM_SAFE_PRICE: "Below the minimum safe price.",
  MISSING_FEE_DATA: "Marketplace fee policy is missing.",
}

const supportingLabels: Record<string, string> = {
  SEO_FIX: "Improve listing",
  HOLD: "Keep current price",
}

const readableCode = (value: string) => value.toLowerCase().replaceAll("_", " ")

function EvidenceFacts({ evidence }: { evidence: DashboardEvidence }) {
  const sourceTimes = [evidence.competitor_observed_at, evidence.inventory_observed_at]
    .filter((value): value is string => value != null)
    .sort((a, b) => Date.parse(b) - Date.parse(a))
  const latestObservation = sourceTimes[0]
  const latestUpdate = evidence.sales_through && (
    !latestObservation || evidence.sales_through > latestObservation.slice(0, 10)
  ) ? evidence.sales_through : formatDateTime(latestObservation)
  const facts = [
    ["Last evidence update", latestUpdate],
    ["Competitor listings", formatDateTime(evidence.competitor_observed_at)],
    ["Competitor freshness at generation", evidence.competitor_freshness ? readableCode(evidence.competitor_freshness) : "Unavailable"],
    ["Inventory snapshot", formatDateTime(evidence.inventory_observed_at)],
    ["Sales history through", evidence.sales_through ?? "Unavailable"],
    ["Available stock · Observed", formatNullableNumber(evidence.available_units)],
    [evidence.daily_sales_rate == null ? "Daily sales rate" : `Daily sales rate · ${evidence.sales_rate_observed ? "Observed" : "Heuristic estimate"}`, formatNullableNumber(evidence.daily_sales_rate)],
  ]
  if (evidence.target_price != null) {
    facts.unshift(["Recommended price", formatRecommendationPrice(evidence.target_price)])
  }
  return (
    <dl className="mt-4 grid gap-3 sm:grid-cols-2">
      {facts.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="break-words text-sm font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

export function PrimaryEvidence({ evidence, lowConfidence }: {
  evidence: DashboardEvidence
  lowConfidence: boolean
}) {
  const notes = evidence.reason_codes.flatMap((code) => reasonLabels[code] ?? [])
  if (lowConfidence) notes.unshift("The available evidence supports only a low-confidence recommendation.")
  if (evidence.competitor_freshness === "STALE") notes.push(reasonLabels.STALE_COMPETITOR_DATA)
  if (evidence.price_blocked) notes.push("MarginGuard blocked a price change.")
  return (
    <>
      <EvidenceFacts evidence={evidence} />
      {notes.length ? (
        <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          {[...new Set(notes)].map((note) => <li key={note}>{note}</li>)}
        </ul>
      ) : null}
    </>
  )
}

export function RecommendationEvidence({ evidence }: { evidence: DashboardEvidence }) {
  const { reorder, forecasts, pricing_candidates: prices, supporting_actions: supporting } = evidence

  return (
    <div className="space-y-4">
      <section className="rounded-xl border bg-background p-4 shadow-sm" aria-labelledby="demand-forecast">
        <h2 id="demand-forecast" className="font-semibold">Demand forecast</h2>
        {forecasts.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">No approved forecasting model was available for these horizons.</p>
        ) : (
          <p className="mt-2 text-sm text-muted-foreground">Expected net units sold at baseline conditions.</p>
        )}
        <dl className="mt-3 grid gap-3 sm:grid-cols-3">
          {horizons.map((days) => {
            const forecast = forecasts.find((item) => item.horizon_days === days)
            const interval = forecast?.uncertainty === "calibrated" ? forecast.prediction_interval : null
            return (
              <div key={days} className="min-w-0 rounded-lg border p-3">
                <dt className="text-sm font-medium">{days}-day demand</dt>
                <dd className="mt-1 text-sm">
                  {forecast ? (
                    <>
                      <p className="font-semibold">{formatNullableNumber(forecast.expected_units)} units</p>
                      <p className="break-words text-muted-foreground">
                        Model prediction · {forecast.method} · {forecast.version}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {forecast.source === "active" ? "Active model" : "Previous approved model"}
                        {" · Data through "}{formatDateTime(forecast.data_cutoff)}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {interval && interval[0] <= forecast.expected_units && forecast.expected_units <= interval[1]
                          ? `Calibrated interval ${formatNullableNumber(interval[0])}–${formatNullableNumber(interval[1])} units`
                          : "Calibrated interval unavailable"}
                      </p>
                    </>
                  ) : "Unavailable"}
                </dd>
              </div>
            )
          })}
        </dl>
      </section>

      {supporting.length ? (
        <section className="rounded-xl border bg-background p-4 shadow-sm" aria-labelledby="supporting-actions">
          <h2 id="supporting-actions" className="font-semibold">Supporting recommendations</h2>
          <ul className="mt-2 space-y-2 text-sm">
            {supporting.map(({ action, source }) => (
              <li key={`${source}:${action}`}>
                <span className="capitalize">{supportingLabels[action] ?? readableCode(action)}</span>
                <span className="text-muted-foreground"> · {readableCode(source)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {reorder ? (
        <section className="rounded-xl border bg-background p-4 shadow-sm" aria-labelledby="reorder-insights">
          <h2 id="reorder-insights" className="font-semibold">Reorder insights</h2>
          <dl className="mt-2 grid gap-3 text-sm sm:grid-cols-2">
            <div><dt>Suggested quantity</dt><dd>{formatNullableNumber(reorder.quantity)}</dd></div>
            <div><dt>Reorder by</dt><dd>{reorder.deadline ?? "Unavailable"}</dd></div>
            <div><dt>Reorder point</dt><dd>{formatNullableNumber(reorder.reorder_point)}</dd></div>
            <div>
              <dt>Lead-time demand</dt>
              <dd>{formatNullableNumber(reorder.lead_time_demand)}
                {reorder.lead_time_demand != null && reorder.demand_source
                  ? reorder.demand_source === "approved_forecast" ? " · Model prediction" : " · Heuristic estimate from recorded sales"
                  : ""}
              </dd>
            </div>
          </dl>
          <p className="mt-3 text-xs text-muted-foreground">
            Stockout probability unavailable
            {reorder.uncertainty === "validated_lead_time_upper_bound" && reorder.validated_demand_upper_bound != null
              ? ` · Validated upper lead-time demand bound ${formatNullableNumber(reorder.validated_demand_upper_bound)} units`
              : ""}
          </p>
        </section>
      ) : null}

      {prices.length ? (
        <details className="rounded-xl border bg-background p-4 shadow-sm">
          <summary className="cursor-pointer rounded font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            Pricing candidate comparison
          </summary>
          <ul className="mt-3 divide-y text-sm">
            {prices.map((candidate) => (
              <li key={candidate.price} className="grid gap-1 py-2 sm:grid-cols-[8rem_1fr]">
                <span className="font-medium">{formatRecommendationPrice(candidate.price)}</span>
                <div className="min-w-0 break-words">
                  {candidate.constraints_passed
                    ? candidate.price_change_eligible === false ? "Passed price constraints · No price change supported" : "Passed price constraints"
                    : "Blocked by price constraints"}
                  {candidate.rejection_reasons.length ? (
                    <p className="text-xs text-muted-foreground">
                      {candidate.rejection_reasons.map((code) => reasonLabels[code] ?? readableCode(code)).join(" · ")}
                    </p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  )
}
