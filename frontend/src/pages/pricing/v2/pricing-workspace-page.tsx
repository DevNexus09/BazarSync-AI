import { ArrowLeft } from "lucide-react"
import { Link, useParams } from "react-router-dom"

import { InlineAlert } from "@/components/common/inline-alert"
import { LoadingState } from "@/components/common/loading-state"
import { PricingSetupRequiredCard } from "@/components/pricing/PricingSetupRequiredCard"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { FreshnessPill } from "@/components/ui/freshness-pill"
import { MARKETPLACE, useProductPricing, useRefreshProductPricing } from "@/hooks/use-pricing-v2"
import { useProduct } from "@/hooks/use-products"
import { getErrorMessage } from "@/utils/errors"

import { CostsAndFees, PriceHistory } from "./components/CostsAndHistory"
import { MarketPositionCard } from "./components/MarketPositionCard"
import { PriceSimulator } from "./components/PriceSimulator"
import { ProfitCurveCard } from "./components/ProfitCurveCard"
import { RecommendationCard } from "./components/RecommendationCard"
import { t } from "./pricing-i18n"

export default function PricingWorkspacePage() {
  const { productId = "" } = useParams()
  const product = useProduct(productId)
  const { analytics, recommendation, policy, fees, history } = useProductPricing(productId)
  const refresh = useRefreshProductPricing(productId)

  if (product.isLoading || analytics.isLoading || recommendation.isLoading || fees.isLoading) {
    return <LoadingState />
  }
  if (product.isError || !product.data) {
    return (
      <EmptyState
        title={t("productNotFound")}
        message={t("productNotFoundMessage")}
        action={<Button asChild variant="outline"><Link to="/app/pricing">{t("backToPricing")}</Link></Button>}
      />
    )
  }

  const item = product.data
  const snapshot = analytics.data ?? null
  const latest = recommendation.data ?? null
  const currentPrice = item.sellingPrice.toFixed(2)
  const missingFees = fees.data?.isDefault ?? false
  const loadError = [analytics, recommendation, policy, fees].find((query) => query.isError)?.error

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <Link to="/app/pricing" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft aria-hidden className="size-4" /> {t("allProducts")}
          </Link>
          <h2 className="heading-font mt-1 text-2xl font-semibold text-foreground">{item.title}</h2>
        </div>
        <FreshnessPill updatedAt={snapshot?.calculatedAt} onRefresh={() => refresh.mutate()} refreshing={refresh.isPending} />
      </div>

      {loadError ? <InlineAlert variant="error" message={getErrorMessage(loadError)} /> : null}
      {refresh.isError ? <InlineAlert variant="error" title={t("checkFailed")} message={getErrorMessage(refresh.error)} /> : null}

      {missingFees ? (
        <PricingSetupRequiredCard productId={item.id} productName={item.title} marketplace={MARKETPLACE} category={item.category} />
      ) : (
        <RecommendationCard
          productId={item.id}
          recommendation={latest}
          analytics={snapshot}
          onRefresh={() => refresh.mutate()}
          refreshing={refresh.isPending}
        />
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <MarketPositionCard analytics={snapshot} yourPrice={currentPrice} />
        <ProfitCurveCard recommendation={missingFees ? null : latest} />
      </div>

      {policy.isSuccess || policy.isError ? (
        <PriceSimulator key={`${currentPrice}-${policy.data?.priceIncrement}`} productId={item.id} currentPrice={currentPrice} policy={policy.data} />
      ) : null}

      <CostsAndFees productId={item.id} analytics={snapshot} fees={fees.data} />
      <PriceHistory history={history.data} />
    </div>
  )
}
