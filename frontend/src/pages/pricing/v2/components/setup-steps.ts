import type { PricingOverview } from "@/services/pricing-v2-service"

import { t } from "../pricing-i18n"

export type SetupStep = {
  key: "fees" | "policy" | "competitors"
  title: string
  description: string
  done: boolean
  href: string
  actionLabel: string
}

/** Setup progress is derived from data that already exists; nothing new is stored. */
export function pricingSetupSteps(
  overview: PricingOverview | undefined,
  feePolicyCount: number | undefined,
  productId?: string,
): SetupStep[] {
  const query = productId ? `?productId=${productId}` : ""
  return [
    {
      key: "fees",
      title: t("stepFees"),
      description: t("stepFeesDescription"),
      done: (feePolicyCount ?? 0) > 0,
      href: `/app/pricing/fee-setup${query}`,
      actionLabel: t("stepFeesAction"),
    },
    {
      key: "policy",
      title: t("stepPolicy"),
      description: t("stepPolicyDescription"),
      done: (overview?.summary.productsWithPricingPolicy ?? 0) > 0,
      href: `/app/pricing/policy-setup${query}`,
      actionLabel: t("stepPolicyAction"),
    },
    {
      key: "competitors",
      title: t("stepCompetitors"),
      description: t("stepCompetitorsDescription"),
      done: (overview?.summary.productsWithCompetitorData ?? 0) > 0,
      href: "/app/competitors",
      actionLabel: t("stepCompetitorsAction"),
    },
  ]
}
