import type { MarketplaceFeePolicyInput } from "@/services/pricing-policy-service"

import { percentToRate } from "./pricing-setup"

export type FeeFormState = {
  productId: string
  marketplace: string
  category: string
  currency: string
  commissionRatePercent: string
  paymentFeeRatePercent: string
  fixedPerOrderFee: string
  fixedPerUnitFee: string
  fulfilmentFee: string
  shippingSubsidy: string
  otherVariableCost: string
  effectiveFrom: string
}

type FieldResult = { value: number } | { error: string }

export function buildMarketplaceFeePayload(
  form: FeeFormState
): { value: MarketplaceFeePolicyInput } | { error: string } {
  const marketplace = form.marketplace.trim()
  const currency = form.currency.trim().toUpperCase()
  if (!marketplace) return { error: "Marketplace is required." }
  if (!currency) return { error: "Currency is required." }
  if (!form.effectiveFrom) return { error: "Effective from date is required." }

  const commission = readRate(form.commissionRatePercent, "Commission rate")
  if ("error" in commission) return commission
  const payment = readRate(form.paymentFeeRatePercent, "Payment fee rate")
  if ("error" in payment) return payment

  const fixedPerOrderFee = readMoney(form.fixedPerOrderFee, "Fixed per order fee")
  if ("error" in fixedPerOrderFee) return fixedPerOrderFee
  const fixedPerUnitFee = readMoney(form.fixedPerUnitFee, "Fixed per unit fee")
  if ("error" in fixedPerUnitFee) return fixedPerUnitFee
  const fulfilmentFee = readMoney(form.fulfilmentFee, "Fulfilment fee")
  if ("error" in fulfilmentFee) return fulfilmentFee
  const shippingSubsidy = readMoney(form.shippingSubsidy, "Shipping subsidy")
  if ("error" in shippingSubsidy) return shippingSubsidy
  const otherVariableCost = readMoney(form.otherVariableCost, "Other variable cost")
  if ("error" in otherVariableCost) return otherVariableCost

  return {
    value: {
      productId: form.productId.trim() || null,
      marketplace,
      category: form.category.trim() || null,
      currency,
      percentageCommissionRate: percentToRate(commission.value),
      paymentFeeRate: percentToRate(payment.value),
      fixedPerOrderFee: fixedPerOrderFee.value,
      fixedPerUnitFee: fixedPerUnitFee.value,
      fulfilmentFee: fulfilmentFee.value,
      shippingSubsidy: shippingSubsidy.value,
      otherVariableCost: otherVariableCost.value,
      effectiveFrom: new Date(`${form.effectiveFrom}T00:00:00.000Z`).toISOString(),
    },
  }
}

function readRate(value: string, label: string): FieldResult {
  const number = Number(value)
  if (!Number.isFinite(number)) return { error: `${label} must be a number.` }
  if (number < 0 || number > 100) {
    return { error: `${label} must be between 0 and 100.` }
  }
  return { value: number }
}

function readMoney(value: string, label: string): FieldResult {
  const number = Number(value || 0)
  if (!Number.isFinite(number)) return { error: `${label} must be a number.` }
  if (number < 0) return { error: `${label} must be zero or positive.` }
  return { value: number }
}
