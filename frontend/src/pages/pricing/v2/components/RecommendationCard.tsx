import { CheckCircle2, Info } from "lucide-react"

import { InlineAlert } from "@/components/common/inline-alert"
import { Button } from "@/components/ui/button"
import { Card, CardBody, CardHeader } from "@/components/ui/card"
import { EmptyState, MissingData } from "@/components/ui/empty-state"
import { HowCalculated } from "@/components/ui/how-calculated"
import { StatusBadge } from "@/components/ui/status-badge"
import { useRecommendationDecision } from "@/hooks/use-pricing-v2"
import { useTrackRecord } from "@/hooks/use-track-record"
import { confidenceBand } from "@/services/recommendation-outcome-service"
import type { PricingAnalytics, PricingRecommendation } from "@/services/pricing-v2-service"
import { formatDateTime, formatMoney } from "@/utils/formatters"
import { getErrorMessage } from "@/utils/errors"

import { confidenceLabel, elasticityLabel, percentLabel } from "../pricing-math"
import { t } from "../pricing-i18n"

function headline(rec: PricingRecommendation): string {
  const to = formatMoney(rec.recommendedPrice)
  const from = formatMoney(rec.currentPrice)
  if (rec.action === "PRICE_LOWER") return t("lowerTo", { to: to ?? "", from: from ?? "" })
  if (rec.action === "PRICE_RAISE") return t("raiseTo", { to: to ?? "", from: from ?? "" })
  return t("keepAt", { from: from ?? "" })
}

function unitsChange(rec: PricingRecommendation): string | null {
  const baseline = rec.candidates.find((item) => item.candidatePrice === rec.currentPrice)?.expectedUnits
  if (!baseline || !rec.expectedUnits || Number(baseline) === 0) return null
  const change = Math.round(((Number(rec.expectedUnits) - Number(baseline)) / Number(baseline)) * 100)
  return t("unitsChange", { sign: change >= 0 ? "+" : "", percent: change })
}

function profitChange(rec: PricingRecommendation): string | null {
  if (rec.profitImpact == null) return null
  const sign = rec.profitImpact.startsWith("-") ? "−" : "+"
  return t("profitChange", { sign, amount: formatMoney(rec.profitImpact.replace(/^-/, "")) ?? "" })
}

function reasons(rec: PricingRecommendation, analytics: PricingAnalytics | null): string[] {
  const out: string[] = []
  const median = analytics?.competitorMedianPrice
  if (median) {
    const gap = Math.round(((Number(rec.currentPrice) - Number(median)) / Number(median)) * 100)
    out.push(
      gap === 0
        ? t("whyMatches")
        : t("whyGap", { percent: Math.abs(gap), direction: gap > 0 ? t("whyAbove") : t("whyBelow"), median: formatMoney(median) ?? "" }),
    )
  }
  if (analytics && analytics.competitorCount > 0) {
    out.push(t("whyInStock", { inStock: analytics.inStockCompetitorCount, total: analytics.competitorCount }))
  }
  if (rec.minimumSafePrice) {
    out.push(t("whySafe", { price: formatMoney(rec.minimumSafePrice) ?? "" }))
  }
  return out
}

export function RecommendationCard({
  productId,
  recommendation,
  analytics,
  onRefresh,
  refreshing,
}: {
  productId: string
  recommendation: PricingRecommendation | null
  analytics: PricingAnalytics | null
  onRefresh: () => void
  refreshing: boolean
}) {
  const decision = useRecommendationDecision(productId)
  const trackRecord = useTrackRecord("PRICING")

  if (!recommendation) {
    return (
      <EmptyState
        title={t("noSuggestion")}
        message={t("noSuggestionMessage")}
        action={<Button onClick={onRefresh} disabled={refreshing}>{t("checkNow")}</Button>}
      />
    )
  }
  if (recommendation.status === "INSUFFICIENT_DATA") {
    return (
      <MissingData
        title={t("insufficientTitle")}
        reason={t("insufficientReason")}
        nextAction={t("insufficientNext")}
        action={<Button variant="outline" size="sm" onClick={onRefresh} disabled={refreshing}>{t("checkAgain")}</Button>}
      />
    )
  }

  // Calibrated confidence: the measured hit rate of past suggestions in the same confidence band.
  const band = trackRecord.data?.enabled ? trackRecord.data.bands[confidenceBand(Number(recommendation.confidenceScore))] : null
  const measured = band?.reliable && band.hitRate != null ? Math.round(band.hitRate * 100) : null
  const isOpen = recommendation.status === "OPEN"
  const impact = [unitsChange(recommendation), profitChange(recommendation), recommendation.marginRate ? t("marginLine", { percent: percentLabel(recommendation.marginRate) ?? "" }) : null].filter(Boolean)
  const why = reasons(recommendation, analytics)

  return (
    <Card aria-labelledby="pricing-recommendation-title">
      <CardHeader
        title={<span id="pricing-recommendation-title">{t("recTitle")}</span>}
        actions={
          <>
            <StatusBadge kind="pricing" value={recommendation.action} />
            <span className="text-xs text-muted-foreground">
              {t("confidence", { level: confidenceLabel(recommendation.confidenceScore) })}
              {measured != null ? t("measured", { percent: measured }) : ""}
            </span>
          </>
        }
      />
      <CardBody className="space-y-3">
        <p className="text-xl font-semibold text-foreground">{headline(recommendation)}</p>
        {impact.length ? <p className="text-sm text-foreground">{impact.join(" · ")}</p> : null}
        {why.length ? (
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{t("whyLabel")}</span>
            {why.join("; ")}
          </p>
        ) : null}

        {isOpen ? (
          recommendation.action === "HOLD" ? null : (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-2">
                <Button
                  onClick={() => decision.mutate({ id: recommendation.id, decision: "acknowledge" })}
                  disabled={decision.isPending}
                >
                  {t("markApplied")}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => decision.mutate({ id: recommendation.id, decision: "dismiss" })}
                  disabled={decision.isPending}
                >
                  {t("dismiss")}
                </Button>
              </div>
              <p className="flex items-center gap-1 text-xs text-muted-foreground">
                <Info aria-hidden className="size-3.5" />
                {t("neverChange")}
              </p>
            </div>
          )
        ) : (
          <p className="flex items-center gap-1 text-sm text-muted-foreground">
            <CheckCircle2 aria-hidden className="size-4" />
            {recommendation.status === "ACKNOWLEDGED"
              ? t("markedApplied")
              : recommendation.status === "DISMISSED"
                ? t("dismissedDot")
                : t("outdated")}{" "}
            <button type="button" className="font-medium text-primary hover:underline disabled:opacity-50" onClick={onRefresh} disabled={refreshing}>
              {t("checkPricesAgain")}
            </button>
          </p>
        )}
        {decision.isError ? <InlineAlert variant="error" message={getErrorMessage(decision.error)} /> : null}

        <HowCalculated
          formula={t("recFormula")}
          version={recommendation.formulaVersion}
          calculatedAt={recommendation.generatedAt}
          assumptions={[
            elasticityLabel(recommendation.estimationMethod, undefined),
            t("assume30"),
            recommendation.expiresAt ? t("validUntil", { date: formatDateTime(recommendation.expiresAt) }) : t("noExpiry"),
          ]}
        />
      </CardBody>
    </Card>
  )
}
