import apiClient from "@/api/client"

export type MarketplaceFeePolicyInput = {
  productId?: string | null
  marketplace: string
  category?: string | null
  currency: string
  percentageCommissionRate: number
  paymentFeeRate: number
  fixedPerOrderFee: number
  fixedPerUnitFee: number
  fulfilmentFee: number
  shippingSubsidy: number
  otherVariableCost: number
  effectiveFrom: string
  effectiveTo?: string | null
  version?: string
}

export type MarketplaceFeePolicy = {
  id: string | null
  sellerId: string
  productId: string | null
  marketplace: string
  category: string | null
  currency: string
  percentageCommissionRate: number
  paymentFeeRate: number
  fixedPerOrderFee: number
  fixedPerUnitFee: number
  fulfilmentFee: number
  shippingSubsidy: number
  otherVariableCost: number
  effectiveFrom: string | null
  effectiveTo: string | null
  source: string
  version: string
  isActive: boolean
  isDefault: boolean
  scope: string
}

type MarketplaceFeePolicyApi = {
  id: string | null
  seller_id: string
  product_id: string | null
  marketplace: string
  category: string | null
  currency: string
  percentage_commission_rate: string | number
  payment_fee_rate: string | number
  fixed_per_order_fee: string | number
  fixed_per_unit_fee: string | number
  fulfilment_fee: string | number
  shipping_subsidy: string | number
  other_variable_cost: string | number
  effective_from: string | null
  effective_to: string | null
  source: string
  version: string
  is_active: boolean
  is_default: boolean
  scope: string
}

type MarketplaceFeePolicyListApi = {
  items: MarketplaceFeePolicyApi[]
  total: number
}

export async function createMarketplaceFeePolicy(
  payload: MarketplaceFeePolicyInput
) {
  const { data } = await apiClient.post<MarketplaceFeePolicyApi>(
    "/pricing-policies/marketplace-fees",
    toApiPayload(payload)
  )
  return mapMarketplaceFeePolicy(data)
}

export async function getEffectiveMarketplaceFeePolicy({
  productId,
  marketplace,
}: {
  productId: string
  marketplace: string
}) {
  const { data } = await apiClient.get<MarketplaceFeePolicyApi>(
    `/pricing-policies/products/${productId}/fees/effective`,
    { params: { marketplace } }
  )
  return mapMarketplaceFeePolicy(data)
}

export async function listMarketplaceFeePolicies({
  productId,
  marketplace,
}: {
  productId?: string | null
  marketplace?: string | null
}) {
  const { data } = await apiClient.get<MarketplaceFeePolicyListApi>(
    "/pricing-policies/marketplace-fees",
    {
      params: {
        product_id: productId || undefined,
        marketplace: marketplace || undefined,
      },
    }
  )
  return {
    items: data.items.map(mapMarketplaceFeePolicy),
    total: data.total,
  }
}

export async function expireMarketplaceFeePolicy({
  feePolicyId,
  effectiveTo,
}: {
  feePolicyId: string
  effectiveTo: string
}) {
  const { data } = await apiClient.patch<MarketplaceFeePolicyApi>(
    `/pricing-policies/marketplace-fees/${feePolicyId}/expire`,
    { effective_to: effectiveTo }
  )
  return mapMarketplaceFeePolicy(data)
}

function toApiPayload(payload: MarketplaceFeePolicyInput) {
  return {
    product_id: payload.productId || null,
    marketplace: payload.marketplace,
    category: payload.category || null,
    currency: payload.currency,
    percentage_commission_rate: payload.percentageCommissionRate,
    payment_fee_rate: payload.paymentFeeRate,
    fixed_per_order_fee: payload.fixedPerOrderFee,
    fixed_per_unit_fee: payload.fixedPerUnitFee,
    fulfilment_fee: payload.fulfilmentFee,
    shipping_subsidy: payload.shippingSubsidy,
    other_variable_cost: payload.otherVariableCost,
    source: "manual",
    version: payload.version || "v1",
    is_active: true,
    effective_from: payload.effectiveFrom,
    effective_to: payload.effectiveTo || null,
  }
}

function mapMarketplaceFeePolicy(
  policy: MarketplaceFeePolicyApi
): MarketplaceFeePolicy {
  return {
    id: policy.id,
    sellerId: policy.seller_id,
    productId: policy.product_id,
    marketplace: policy.marketplace,
    category: policy.category,
    currency: policy.currency,
    percentageCommissionRate: toNumber(policy.percentage_commission_rate),
    paymentFeeRate: toNumber(policy.payment_fee_rate),
    fixedPerOrderFee: toNumber(policy.fixed_per_order_fee),
    fixedPerUnitFee: toNumber(policy.fixed_per_unit_fee),
    fulfilmentFee: toNumber(policy.fulfilment_fee),
    shippingSubsidy: toNumber(policy.shipping_subsidy),
    otherVariableCost: toNumber(policy.other_variable_cost),
    effectiveFrom: policy.effective_from,
    effectiveTo: policy.effective_to,
    source: policy.source,
    version: policy.version,
    isActive: policy.is_active,
    isDefault: policy.is_default,
    scope: policy.scope,
  }
}

function toNumber(value: string | number) {
  return typeof value === "number" ? value : Number(value)
}
