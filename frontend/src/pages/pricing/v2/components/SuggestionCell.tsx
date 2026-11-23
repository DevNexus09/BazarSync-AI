import { StatusBadge } from "@/components/ui/status-badge"
import { t } from "../pricing-i18n"
import type { PricingOverviewRow } from "@/services/pricing-v2-service"
import { formatMoney } from "@/utils/formatters"

export function SuggestionCell({ recommendation }: { recommendation: PricingOverviewRow["recommendation"] }) {
  if (!recommendation) {
    return <span className="text-muted-foreground">{t("suggestionNone")}</span>
  }
  if (recommendation.isActionable) {
    return (
      <span className="inline-flex items-center gap-2">
        <StatusBadge kind="pricing" value={recommendation.action} />
        <span className="font-medium">→ {formatMoney(recommendation.recommendedPrice)}</span>
      </span>
    )
  }
  const settled: Record<string, string> = {
    ACKNOWLEDGED: t("suggestionApplied"),
    DISMISSED: t("suggestionDismissed"),
    EXPIRED: t("suggestionExpired"),
  }
  return recommendation.action === "HOLD" && recommendation.status === "OPEN" ? (
    <StatusBadge kind="pricing" value="HOLD" />
  ) : (
    <span className="text-muted-foreground">{settled[recommendation.status] ?? t("suggestionExpired")}</span>
  )
}
