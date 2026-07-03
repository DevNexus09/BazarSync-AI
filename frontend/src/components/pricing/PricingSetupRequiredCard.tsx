import { Link } from "react-router-dom"
import { CircleDollarSign, ShieldAlert } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  buildMarketplaceFeeSetupPath,
  type MarketplaceFeeSetupParams,
} from "@/utils/pricing-setup"

type PricingSetupRequiredCardProps = MarketplaceFeeSetupParams & {
  productName?: string
}

export function PricingSetupRequiredCard({
  productId,
  productName,
  marketplace = "Daraz Bangladesh",
  category,
  currency = "BDT",
}: PricingSetupRequiredCardProps) {
  const setupPath = buildMarketplaceFeeSetupPath({
    productId,
    marketplace,
    category,
    currency,
  })

  return (
    <section className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 shadow-sm">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="flex gap-3">
          <span className="mt-0.5 inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-amber-500/15 text-amber-500">
            <ShieldAlert className="size-5" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-500">
              Pricing setup incomplete
            </p>
            <h3 className="mt-1 text-base font-semibold text-foreground">
              Marketplace fee data is missing.
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Add a fee policy to unlock revenue and profit simulation.
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              The simulator needs marketplace commission, payment fees, and
              other selling costs before it can safely calculate expected profit.
            </p>
            {productName ? (
              <p className="mt-3 text-xs text-muted-foreground">
                Product: <span className="font-medium text-foreground">{productName}</span>
              </p>
            ) : null}
          </div>
        </div>
        <Button asChild className="w-full md:w-auto">
          <Link to={setupPath}>
            <CircleDollarSign className="size-4" aria-hidden="true" />
            Set Up Marketplace Fees
          </Link>
        </Button>
      </div>
    </section>
  )
}
