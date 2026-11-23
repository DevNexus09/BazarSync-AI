import { ChevronRight } from "lucide-react"
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { MarketplaceFeePolicy } from "@/services/pricing-policy-service"
import type { PricingAnalytics } from "@/services/pricing-v2-service"
import { formatMoney } from "@/utils/formatters"

import { t } from "../pricing-i18n"

function Section({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <details className="group glass-panel-muted">
      <summary className="flex cursor-pointer list-none items-center gap-1 px-4 py-3 text-sm font-medium text-foreground">
        <ChevronRight aria-hidden className="size-4 transition group-open:rotate-90" />
        {title}
      </summary>
      <div className="px-4 pb-4">{children}</div>
    </details>
  )
}

const rate = (value: number) => `${(value * 100).toFixed(1)}%`

export function CostsAndFees({
  productId,
  analytics,
  fees,
}: {
  productId: string
  analytics: PricingAnalytics | null
  fees: MarketplaceFeePolicy | undefined
}) {
  const summary = [
    analytics ? t("costSummary", { amount: formatMoney(analytics.unitCost) ?? "" }) : null,
    fees && !fees.isDefault ? t("commissionSummary", { rate: rate(fees.percentageCommissionRate) }) : t("noFeesSummary"),
  ]
    .filter(Boolean)
    .join(", ")
  return (
    <Section title={t("costsTitle", { summary })}>
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
        <Item label={t("unitCost")} value={analytics ? formatMoney(analytics.unitCost) : t("notCalculated")} />
        {fees && !fees.isDefault ? (
          <>
            <Item label={t("commission")} value={rate(fees.percentageCommissionRate)} />
            <Item label={t("paymentFee")} value={rate(fees.paymentFeeRate)} />
            <Item label={t("perOrder")} value={formatMoney(fees.fixedPerOrderFee)} />
            <Item label={t("perUnit")} value={formatMoney(fees.fixedPerUnitFee)} />
            <Item label={t("fulfilment")} value={formatMoney(fees.fulfilmentFee)} />
          </>
        ) : null}
        {analytics ? <Item label={t("safeMinimum")} value={formatMoney(analytics.minimumSafePrice)} /> : null}
      </dl>
      <Link className="mt-3 inline-block text-sm font-medium text-primary hover:underline" to={`/app/pricing/fee-setup?productId=${productId}`}>
        {t("editFees")}
      </Link>
    </Section>
  )
}

function Item({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium text-foreground">{value ?? "—"}</dd>
    </div>
  )
}

const axisTick = { fill: "rgb(var(--muted-foreground))", fontSize: 11 }
const dayLabel = (iso: string) => new Intl.DateTimeFormat("en-BD", { day: "numeric", month: "short" }).format(new Date(iso))

export function PriceHistory({ history }: { history: PricingAnalytics[] | undefined }) {
  const points = [...(history ?? [])]
    .sort((a, b) => a.calculatedAt.localeCompare(b.calculatedAt))
    .map((item) => ({
      day: dayLabel(item.calculatedAt),
      yours: Number(item.currentPrice),
      market: item.competitorMedianPrice == null ? null : Number(item.competitorMedianPrice),
    }))
  return (
    <Section title={t("historyTitle")}>
      {points.length < 2 ? (
        <p className="text-sm text-muted-foreground">{t("historyEmpty")}</p>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
              <CartesianGrid stroke="rgb(var(--border))" strokeOpacity={0.4} vertical={false} />
              <XAxis dataKey="day" tick={axisTick} minTickGap={24} />
              <YAxis tick={axisTick} width={56} domain={["auto", "auto"]} tickFormatter={(v: number) => `৳${Math.round(v)}`} />
              <Tooltip
                formatter={(value) => formatMoney(Number(value)) ?? ""}
                contentStyle={{
                  background: "rgb(var(--tooltip-background))",
                  border: "1px solid rgb(var(--tooltip-border))",
                  borderRadius: 8,
                  color: "rgb(var(--tooltip-foreground))",
                }}
                labelStyle={{ color: "rgb(var(--tooltip-foreground))" }}
                itemStyle={{ color: "rgb(var(--tooltip-foreground))" }}
              />
              <Legend wrapperStyle={{ color: "rgb(var(--muted-foreground))", fontSize: 12 }} />
              <Line name={t("yourPriceSeries")} dataKey="yours" stroke="rgb(var(--chart-1))" strokeWidth={2} dot={false} isAnimationActive={false} />
              {/* Dashed as well as a different shade, so the two lines differ without colour. */}
              <Line name={t("marketSeries")} dataKey="market" stroke="rgb(var(--chart-2))" strokeWidth={2} strokeDasharray="6 4" dot={false} connectNulls isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Section>
  )
}
