import { CheckCircle2, Circle } from "lucide-react"
import { Link } from "react-router-dom"

import { LoadingState } from "@/components/common/loading-state"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { useMarketplaceFeePolicies, usePricingOverview } from "@/hooks/use-pricing-v2"

import { pricingSetupSteps } from "./components/setup-steps"
import { t } from "./pricing-i18n"

export default function PricingSetupPage() {
  const overview = usePricingOverview()
  const fees = useMarketplaceFeePolicies()
  if (overview.isLoading || fees.isLoading) {
    return <LoadingState />
  }
  const steps = pricingSetupSteps(overview.data, fees.data?.total)
  const done = steps.filter((step) => step.done).length

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("setupTitle")}
        description={t("setupDone", { done, total: steps.length })}
        action={<Button asChild variant="outline"><Link to="/app/pricing">{t("backToPricing")}</Link></Button>}
      />
      <ol className="space-y-3">
        {steps.map((step, index) => {
          const Icon = step.done ? CheckCircle2 : Circle
          return (
            <li key={step.key}>
              <Card>
                <CardBody className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex gap-3">
                    <Icon aria-hidden className={step.done ? "mt-0.5 size-5 text-success" : "mt-0.5 size-5 text-muted-foreground"} />
                    <div>
                      <h3 className="font-semibold text-foreground">
                        {index + 1}. {step.title}
                        <span className={step.done ? "ml-2 text-xs font-medium text-success" : "ml-2 text-xs font-medium text-muted-foreground"}>
                          {step.done ? t("done") : t("toDo")}
                        </span>
                      </h3>
                      <p className="text-sm text-muted-foreground">{step.description}</p>
                    </div>
                  </div>
                  <Button asChild variant={step.done ? "outline" : "default"} size="sm">
                    <Link to={step.href}>{step.done ? t("review") : step.actionLabel}</Link>
                  </Button>
                </CardBody>
              </Card>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
