import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { Card, CardBody, CardHeader } from "@/components/ui/card"
import type { PricingRecommendation } from "@/services/pricing-v2-service"
import { formatMoney } from "@/utils/formatters"

import { profitCurvePoints, type ProfitPoint as Point } from "../pricing-math"
import { t } from "../pricing-i18n"

const axisTick = { fill: "rgb(var(--muted-foreground))", fontSize: 11 }

function PointTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: Point }> }) {
  const point = active ? payload?.[0]?.payload : undefined
  if (!point) return null
  return (
    <div className="rounded-md border border-[rgb(var(--tooltip-border))] bg-[rgb(var(--tooltip-background))] px-2 py-1 text-xs text-[rgb(var(--tooltip-foreground))] shadow-lg">
      <div className="font-semibold">{point.priceText}</div>
      <div>{t("profitTooltip", { amount: point.profitText })}</div>
      {point.allowed ? null : <div>{t("notAllowed", { reasons: point.reasons.join(", ") || t("breaksRules") })}</div>}
    </div>
  )
}

export function ProfitCurveCard({ recommendation }: { recommendation: PricingRecommendation | null }) {
  const points = profitCurvePoints(recommendation)
  if (points.length < 2 || !recommendation) {
    return (
      <Card>
        <CardHeader title={t("profitTitle")} />
        <CardBody>
          <p className="text-sm text-muted-foreground">
            {t("profitEmpty")}
          </p>
        </CardBody>
      </Card>
    )
  }
  const safeMin = recommendation.minimumSafePrice ? Number(recommendation.minimumSafePrice) : null
  const lowest = points[0].price
  const recommended = Number(recommendation.recommendedPrice)

  return (
    <Card>
      <CardHeader
        title={t("profitTitle")}
        description={safeMin != null ? t("profitShaded", { price: formatMoney(recommendation.minimumSafePrice) ?? "" }) : undefined}
      />
      <CardBody>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
              <CartesianGrid stroke="rgb(var(--border))" strokeOpacity={0.4} vertical={false} />
              <XAxis dataKey="price" type="number" domain={["dataMin", "dataMax"]} tick={axisTick} tickFormatter={(v: number) => `৳${v}`} />
              <YAxis tick={axisTick} width={56} tickFormatter={(v: number) => `৳${Math.round(v)}`} />
              {safeMin != null && safeMin > lowest ? (
                <ReferenceArea x1={lowest} x2={safeMin} fill="rgb(var(--danger))" fillOpacity={0.12} stroke="none" ifOverflow="hidden" />
              ) : null}
              <ReferenceLine x={recommended} stroke="rgb(var(--foreground))" strokeDasharray="4 4" label={{ value: t("suggestedMark"), fill: "rgb(var(--muted-foreground))", fontSize: 11, position: "top" }} />
              <Tooltip content={<PointTooltip />} cursor={{ stroke: "rgb(var(--muted-foreground))", strokeDasharray: "3 3" }} />
              <Line
                type="monotone"
                dataKey="profit"
                stroke="rgb(var(--chart-1))"
                strokeWidth={2}
                isAnimationActive={false}
                dot={(props: { cx?: number; cy?: number; payload?: Point; index?: number }) => (
                  <circle
                    key={props.index}
                    cx={props.cx}
                    cy={props.cy}
                    r={4}
                    strokeWidth={2}
                    stroke="rgb(var(--chart-1))"
                    fill={props.payload?.allowed ? "rgb(var(--chart-1))" : "rgb(var(--card))"}
                  />
                )}
                activeDot={{ r: 6, stroke: "rgb(var(--card))", strokeWidth: 2 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{t("dotsLegend")}</p>
      </CardBody>
    </Card>
  )
}
