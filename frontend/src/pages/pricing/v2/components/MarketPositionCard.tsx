import { Link } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { Card, CardBody, CardHeader } from "@/components/ui/card"
import { MissingData } from "@/components/ui/empty-state"
import type { PricingAnalytics } from "@/services/pricing-v2-service"
import { formatMoney } from "@/utils/formatters"

import { t } from "../pricing-i18n"

type Point = { label: string; value: string }

/** Horizontal box plot of competitor prices with the seller's price marked. Plain HTML so every value is also text. */
export function MarketPositionCard({ analytics, yourPrice }: { analytics: PricingAnalytics | null; yourPrice: string }) {
  const count = analytics?.competitorCount ?? 0
  const footer = analytics
    ? t("competitorFooter", { count, competitors: count === 1 ? t("competitorOne") : t("competitorMany"), inStock: analytics.inStockCompetitorCount })
    : null

  if (!analytics || count === 0 || !analytics.competitorMinPrice || !analytics.competitorMaxPrice) {
    return (
      <Card>
        <CardHeader title={t("marketTitle")} />
        <CardBody>
          <MissingData
            title={t("noCompetitors")}
            reason={t("noCompetitorsReason")}
            action={
              <Button asChild variant="outline" size="sm">
                <Link to="/app/competitors">{t("trackCompetitors")}</Link>
              </Button>
            }
          />
        </CardBody>
      </Card>
    )
  }

  if (count < 3) {
    const prices = [...new Set([analytics.competitorMinPrice, analytics.competitorMaxPrice])]
    return (
      <Card>
        <CardHeader title={t("marketTitle")} description={t("fewCompetitors")} />
        <CardBody className="space-y-2 text-sm">
          <p>
            {prices.length > 1 ? t("competitorPricesLabel") : t("competitorPriceLabel")} <span className="font-medium text-foreground">{prices.map((p) => formatMoney(p)).join(", ")}</span>
          </p>
          <p>
            {t("youLabel")} <span className="font-medium text-foreground">{formatMoney(yourPrice)}</span>
          </p>
          <p className="text-xs text-muted-foreground">{footer}</p>
        </CardBody>
      </Card>
    )
  }

  const points: Point[] = [
    { label: t("pointLowest"), value: analytics.competitorMinPrice },
    { label: t("pointQ1"), value: analytics.competitorQ1Price ?? analytics.competitorMinPrice },
    { label: t("pointMedian"), value: analytics.competitorMedianPrice ?? analytics.competitorMinPrice },
    { label: t("pointQ3"), value: analytics.competitorQ3Price ?? analytics.competitorMaxPrice },
    { label: t("pointHighest"), value: analytics.competitorMaxPrice },
  ]
  // Position on the axis only; values shown are the exact strings.
  const all = [...points.map((p) => Number(p.value)), Number(yourPrice)]
  const lo = Math.min(...all)
  const hi = Math.max(...all)
  const pct = (value: string) => (hi === lo ? 50 : ((Number(value) - lo) / (hi - lo)) * 100)
  const [min, q1, median, q3, max] = points.map((p) => pct(p.value))
  const you = pct(yourPrice)

  return (
    <Card>
      <CardHeader title={t("marketTitle")} />
      <CardBody className="space-y-3">
        <div className="relative h-16" role="img" aria-label={t("boxAria", { low: formatMoney(points[0].value) ?? "", high: formatMoney(points[4].value) ?? "", median: formatMoney(points[2].value) ?? "", you: formatMoney(yourPrice) ?? "" })}>
          <div className="absolute top-6 h-0.5 bg-muted-foreground/50" style={{ left: `${min}%`, width: `${max - min}%` }} />
          <div className="absolute top-3 h-6 rounded-[4px] border-2 border-[rgb(var(--chart-1))] bg-[rgb(var(--chart-1)/0.2)]" style={{ left: `${q1}%`, width: `${Math.max(q3 - q1, 0.5)}%` }} />
          <div className="absolute top-2 h-8 w-0.5 bg-foreground" style={{ left: `${median}%` }} />
          {[min, max].map((left, index) => (
            <div key={index} className="absolute top-4 h-4 w-0.5 bg-muted-foreground" style={{ left: `${left}%` }} />
          ))}
          <div className="absolute top-10 -translate-x-1/2 text-center text-xs font-semibold text-foreground" style={{ left: `${you}%` }}>
            <span aria-hidden>▲</span>
            <span className="block whitespace-nowrap">{t("youMarker", { price: formatMoney(yourPrice) ?? "" })}</span>
          </div>
        </div>
        <dl className="mt-6 grid grid-cols-5 gap-1 text-center text-xs">
          {points.map((point) => (
            <div key={point.label}>
              <dt className="text-muted-foreground">{point.label}</dt>
              <dd className="font-medium text-foreground">{formatMoney(point.value)}</dd>
            </div>
          ))}
        </dl>
        <p className="text-xs text-muted-foreground">{footer}</p>
      </CardBody>
    </Card>
  )
}
