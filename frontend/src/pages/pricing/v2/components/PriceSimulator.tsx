import { useQuery } from "@tanstack/react-query"
import { AlertTriangle } from "lucide-react"
import { useEffect, useId, useState } from "react"

import { Card, CardBody, CardHeader } from "@/components/ui/card"
import type { PricingPolicy } from "@/services/pricing-v2-service"
import { simulateRevenue } from "@/services/pricing-simulator-service"
import { formatMoney, formatNumber } from "@/utils/formatters"
import { getErrorMessage } from "@/utils/errors"

import { elasticityLabel, fromPaisa, rejectionLabel, sliderBounds } from "../pricing-math"
import { t } from "../pricing-i18n"

const DEBOUNCE_MS = 300

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return debounced
}

export function PriceSimulator({
  productId,
  currentPrice,
  policy,
}: {
  productId: string
  currentPrice: string
  policy: PricingPolicy | undefined
}) {
  const bounds = sliderBounds(currentPrice, policy)
  const [paisa, setPaisa] = useState(bounds.value)
  const price = fromPaisa(paisa)
  const debouncedPrice = useDebounced(price, DEBOUNCE_MS)
  const sliderId = useId()

  const simulation = useQuery({
    queryKey: ["pricing-v2", "product", productId, "simulate", debouncedPrice],
    queryFn: () => simulateRevenue(productId, { candidatePrices: [Number(debouncedPrice)], forecastHorizonDays: 30 }),
    staleTime: 60_000,
    placeholderData: (previous) => previous,
  })
  const scenario = simulation.data?.scenarios[0]
  const stepText = formatMoney(fromPaisa(bounds.step))

  return (
    <Card>
      <CardHeader title={t("simTitle")} description={t("simDescription", { step: stepText ?? "" })} />
      <CardBody className="space-y-4">
        <div className="space-y-2">
          <label htmlFor={sliderId} className="flex items-baseline justify-between text-sm">
            <span className="font-medium text-foreground">{t("price")}</span>
            <span className="text-lg font-semibold text-foreground">{formatMoney(price)}</span>
          </label>
          <input
            id={sliderId}
            type="range"
            min={bounds.min}
            max={bounds.max}
            step={bounds.step}
            value={paisa}
            onChange={(event) => setPaisa(Number(event.target.value))}
            aria-valuetext={formatMoney(price) ?? price}
            className="w-full accent-[rgb(var(--primary))]"
          />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{formatMoney(fromPaisa(bounds.min))}</span>
            <span>{t("todayPrice", { price: formatMoney(currentPrice) ?? "" })}</span>
            <span>{formatMoney(fromPaisa(bounds.max))}</span>
          </div>
        </div>

        {simulation.isError ? (
          <p className="text-sm text-danger">{getErrorMessage(simulation.error)}</p>
        ) : scenario ? (
          <div aria-live="polite" aria-busy={simulation.isFetching} className="space-y-2">
            {scenario.isAllowed ? (
              <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <Metric label={t("units30")} value={scenario.expectedUnits == null ? "—" : formatNumber(Math.round(scenario.expectedUnits))} />
                <Metric label={t("revenue")} value={formatMoney(scenario.expectedRevenue) ?? "—"} />
                <Metric label={t("profit")} value={formatMoney(scenario.expectedProfit) ?? "—"} />
                <Metric label={t("margin")} value={scenario.marginRate == null ? "—" : `${(scenario.marginRate * 100).toFixed(1)}%`} />
              </dl>
            ) : (
              <p className="flex items-start gap-2 rounded-lg border border-danger/40 bg-danger/10 p-2 text-sm text-foreground">
                <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
                {t("notAllowedSentence", { reasons: scenario.rejectionReasons.map(rejectionLabel).join(", ") || t("breaksRules") })}
              </p>
            )}
            <p className="text-xs text-muted-foreground" data-testid="elasticity-source">
              {elasticityLabel(simulation.data?.demandMethod, simulation.data?.evidence?.elasticity)}
            </p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t("calculating")}</p>
        )}
      </CardBody>
    </Card>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-semibold text-foreground">{value}</dd>
    </div>
  )
}
