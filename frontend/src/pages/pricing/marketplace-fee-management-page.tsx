import axios from "axios"
import { ArrowLeft, CircleAlert, History, Plus, Save, TimerOff } from "lucide-react"
import { useMemo, useState } from "react"
import type { FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { InlineAlert } from "@/components/common/inline-alert"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useProducts } from "@/hooks/use-products"
import {
  createMarketplaceFeePolicy,
  expireMarketplaceFeePolicy,
  listMarketplaceFeePolicies,
  type MarketplaceFeePolicy,
  type MarketplaceFeePolicyInput,
} from "@/services/pricing-policy-service"
import { getErrorMessage } from "@/utils/errors"
import { formatDateTime, formatNumber } from "@/utils/formatters"
import { percentToRate } from "@/utils/pricing-setup"

type VersionFormState = {
  marketplace: string
  category: string
  currency: string
  version: string
  commissionRatePercent: string
  paymentFeeRatePercent: string
  fixedPerOrderFee: string
  fixedPerUnitFee: string
  fulfilmentFee: string
  shippingSubsidy: string
  otherVariableCost: string
  effectiveFrom: string
}

type NumberFieldResult = { value: number } | { error: string }

const today = () => new Date().toISOString().slice(0, 10)

export default function MarketplaceFeeManagementPage() {
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [selectedProductId, setSelectedProductId] = useState(
    () => searchParams.get("productId") ?? ""
  )
  const [message, setMessage] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [expireDateById, setExpireDateById] = useState<Record<string, string>>({})

  const { data: products } = useProducts()
  const activeProductId = selectedProductId || products?.[0]?.id || ""
  const selectedProduct = products?.find((product) => product.id === activeProductId)
  const marketplace = searchParams.get("marketplace") ?? "Daraz Bangladesh"

  const feeQueryKey = ["marketplace-fee-policies", activeProductId, marketplace]
  const policiesQuery = useQuery({
    queryKey: feeQueryKey,
    queryFn: () =>
      listMarketplaceFeePolicies({
        productId: activeProductId,
        marketplace,
      }),
    enabled: Boolean(activeProductId),
    staleTime: 15_000,
  })

  const policies = useMemo(
    () => policiesQuery.data?.items ?? [],
    [policiesQuery.data?.items]
  )
  const nextVersion = useMemo(() => buildNextVersion(policies), [policies])
  const [form, setForm] = useState<VersionFormState>(() => ({
    marketplace,
    category: searchParams.get("category") ?? "",
    currency: searchParams.get("currency") ?? "BDT",
    version: "v2",
    commissionRatePercent: "",
    paymentFeeRatePercent: "",
    fixedPerOrderFee: "0",
    fixedPerUnitFee: "0",
    fulfilmentFee: "0",
    shippingSubsidy: "0",
    otherVariableCost: "0",
    effectiveFrom: today(),
  }))

  const syncFormWithLatest = () => {
    const latest = policies[0]
    setForm((current) => ({
      ...current,
      marketplace,
      category: selectedProduct?.category ?? latest?.category ?? current.category,
      currency: latest?.currency ?? current.currency,
      version: nextVersion,
      commissionRatePercent: latest ? rateToPercent(latest.percentageCommissionRate) : current.commissionRatePercent,
      paymentFeeRatePercent: latest ? rateToPercent(latest.paymentFeeRate) : current.paymentFeeRatePercent,
      fixedPerOrderFee: latest ? String(latest.fixedPerOrderFee) : current.fixedPerOrderFee,
      fixedPerUnitFee: latest ? String(latest.fixedPerUnitFee) : current.fixedPerUnitFee,
      fulfilmentFee: latest ? String(latest.fulfilmentFee) : current.fulfilmentFee,
      shippingSubsidy: latest ? String(latest.shippingSubsidy) : current.shippingSubsidy,
      otherVariableCost: latest ? String(latest.otherVariableCost) : current.otherVariableCost,
    }))
  }

  const createMutation = useMutation({
    mutationFn: (payload: MarketplaceFeePolicyInput) =>
      createMarketplaceFeePolicy(payload),
    onSuccess: async () => {
      setMessage("New marketplace fee version saved successfully.")
      await queryClient.invalidateQueries({ queryKey: feeQueryKey })
      await queryClient.invalidateQueries({ queryKey: ["pricing"] })
    },
  })

  const expireMutation = useMutation({
    mutationFn: (payload: { feePolicyId: string; effectiveTo: string }) =>
      expireMarketplaceFeePolicy(payload),
    onSuccess: async () => {
      setMessage("Fee policy expiry date saved successfully.")
      await queryClient.invalidateQueries({ queryKey: feeQueryKey })
      await queryClient.invalidateQueries({ queryKey: ["pricing"] })
    },
  })

  const submitNewVersion = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFormError(null)
    setMessage(null)
    const payload = buildVersionPayload(form, activeProductId)
    if ("error" in payload) {
      setFormError(payload.error)
      return
    }
    createMutation.mutate(payload.value)
  }

  const expirePolicy = (policy: MarketplaceFeePolicy) => {
    if (!policy.id) return
    const date = expireDateById[policy.id]
    if (!date) {
      setFormError("Choose an effective to date before expiring a policy.")
      return
    }
    setFormError(null)
    setMessage(null)
    expireMutation.mutate({
      feePolicyId: policy.id,
      effectiveTo: new Date(`${date}T00:00:00.000Z`).toISOString(),
    })
  }

  const error =
    formError ||
    policyErrorMessage(createMutation.error) ||
    policyErrorMessage(expireMutation.error) ||
    (policiesQuery.error
      ? getErrorMessage(policiesQuery.error, "Could not load fee policies.")
      : null)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Market Policy Fee"
        description="Review marketplace fees, create a new version, or expire an old fee policy."
        action={
          <Button asChild variant="outline">
            <Link to={`/app/pricing${activeProductId ? `?productId=${activeProductId}` : ""}`}>
              <ArrowLeft className="size-4" aria-hidden="true" />
              Back to Pricing Analytics
            </Link>
          </Button>
        }
      />

      <section className="rounded-xl border border-border/70 bg-card p-4 shadow-sm">
        <div className="grid gap-4 md:grid-cols-[1fr_auto] md:items-end">
          <div className="space-y-2">
            <label
              htmlFor="fee-product"
              className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
            >
              Product
            </label>
            <select
              id="fee-product"
              value={activeProductId}
              onChange={(event) => setSelectedProductId(event.target.value)}
              className="h-11 w-full rounded-xl border border-border/70 bg-card/70 px-3 text-sm text-foreground outline-none focus-visible:border-primary/60 focus-visible:ring-2 focus-visible:ring-primary/30"
            >
              {products?.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.title}
                </option>
              ))}
            </select>
          </div>
          <Button type="button" variant="outline" onClick={syncFormWithLatest}>
            <History className="size-4" aria-hidden="true" />
            Copy Latest Into New Version
          </Button>
        </div>
      </section>

      {error ? <InlineAlert variant="error" message={error} /> : null}
      {message ? <InlineAlert variant="success" message={message} /> : null}

      <section className="rounded-xl border border-border/70 bg-card shadow-sm">
        <div className="border-b border-border/60 p-4">
          <h3 className="text-base font-semibold text-foreground">
            Existing fee policies
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            The latest active matching policy is used by Pricing Analytics.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr className="border-b border-border/60">
                <th className="px-4 py-3">Version</th>
                <th className="px-4 py-3">Scope</th>
                <th className="px-4 py-3">Commission</th>
                <th className="px-4 py-3">Payment fee</th>
                <th className="px-4 py-3">Fixed costs</th>
                <th className="px-4 py-3">Effective from</th>
                <th className="px-4 py-3">Effective to</th>
                <th className="px-4 py-3">Expire</th>
              </tr>
            </thead>
            <tbody>
              {policies.map((policy) => (
                <tr key={policy.id ?? policy.version} className="border-b border-border/40 last:border-0">
                  <td className="px-4 py-3 font-medium text-foreground">
                    {policy.version}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {policy.scope}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {rateToPercent(policy.percentageCommissionRate)}%
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {rateToPercent(policy.paymentFeeRate)}%
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    BDT {formatNumber(totalFixedCosts(policy))}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatDateTime(policy.effectiveFrom)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {policy.effectiveTo ? formatDateTime(policy.effectiveTo) : "Still active"}
                  </td>
                  <td className="px-4 py-3">
                    {policy.id ? (
                      <div className="flex gap-2">
                        <Input
                          type="date"
                          value={expireDateById[policy.id] ?? ""}
                          onChange={(event) =>
                            setExpireDateById((current) => ({
                              ...current,
                              [policy.id as string]: event.target.value,
                            }))
                          }
                          className="w-40"
                        />
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => expirePolicy(policy)}
                          disabled={expireMutation.isPending}
                        >
                          <TimerOff className="size-4" aria-hidden="true" />
                          Expire
                        </Button>
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
              {!policiesQuery.isLoading && policies.length === 0 ? (
                <tr>
                  <td className="px-4 py-6 text-center text-muted-foreground" colSpan={8}>
                    No fee policy found for this product yet. Create the first version below.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <form
        onSubmit={submitNewVersion}
        className="rounded-xl border border-border/70 bg-card p-4 shadow-sm"
      >
        <div className="flex items-start gap-3">
          <span className="inline-flex size-10 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Plus className="size-5" aria-hidden="true" />
          </span>
          <div>
            <h3 className="text-base font-semibold text-foreground">
              Create new fee version
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              This preserves old fee records and makes the new version effective from the selected date.
            </p>
          </div>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Marketplace" value={form.marketplace} onChange={(value) => setForm((current) => ({ ...current, marketplace: value }))} />
          <Field label="Category" value={form.category} onChange={(value) => setForm((current) => ({ ...current, category: value }))} />
          <Field label="Currency" value={form.currency} onChange={(value) => setForm((current) => ({ ...current, currency: value.toUpperCase() }))} />
          <Field label="Version" value={form.version || nextVersion} onChange={(value) => setForm((current) => ({ ...current, version: value }))} />
          <Field label="Commission rate" suffix="%" type="number" value={form.commissionRatePercent} onChange={(value) => setForm((current) => ({ ...current, commissionRatePercent: value }))} />
          <Field label="Payment fee rate" suffix="%" type="number" value={form.paymentFeeRatePercent} onChange={(value) => setForm((current) => ({ ...current, paymentFeeRatePercent: value }))} />
          <Field label="Fixed per order fee" type="number" value={form.fixedPerOrderFee} onChange={(value) => setForm((current) => ({ ...current, fixedPerOrderFee: value }))} />
          <Field label="Fixed per unit fee" type="number" value={form.fixedPerUnitFee} onChange={(value) => setForm((current) => ({ ...current, fixedPerUnitFee: value }))} />
          <Field label="Fulfilment fee" type="number" value={form.fulfilmentFee} onChange={(value) => setForm((current) => ({ ...current, fulfilmentFee: value }))} />
          <Field label="Shipping subsidy" type="number" value={form.shippingSubsidy} onChange={(value) => setForm((current) => ({ ...current, shippingSubsidy: value }))} />
          <Field label="Other variable cost" type="number" value={form.otherVariableCost} onChange={(value) => setForm((current) => ({ ...current, otherVariableCost: value }))} />
          <Field label="Effective from date" type="date" value={form.effectiveFrom} onChange={(value) => setForm((current) => ({ ...current, effectiveFrom: value }))} />
        </div>

        <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="inline-flex items-start gap-2 text-sm text-muted-foreground">
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            Create a new version when fees change. Expire old versions instead of editing history.
          </p>
          <Button type="submit" disabled={createMutation.isPending || !activeProductId}>
            {createMutation.isPending ? (
              "Saving..."
            ) : (
              <>
                <Save className="size-4" aria-hidden="true" />
                Save New Version
              </>
            )}
          </Button>
        </div>
      </form>
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  suffix,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: "text" | "number" | "date"
  suffix?: string
}) {
  const id = label.toLowerCase().replaceAll(" ", "-")
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </label>
      <div className="relative">
        <Input
          id={id}
          type={type}
          min={type === "number" ? 0 : undefined}
          step={type === "number" ? "0.01" : undefined}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={suffix ? "pr-10" : undefined}
        />
        {suffix ? (
          <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-muted-foreground">
            {suffix}
          </span>
        ) : null}
      </div>
    </div>
  )
}

function buildVersionPayload(
  form: VersionFormState,
  productId: string
): { value: MarketplaceFeePolicyInput } | { error: string } {
  if (!productId) return { error: "Select a product first." }
  if (!form.marketplace.trim()) return { error: "Marketplace is required." }
  if (!form.currency.trim()) return { error: "Currency is required." }
  if (!form.version.trim()) return { error: "Version is required." }
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
      productId,
      marketplace: form.marketplace.trim(),
      category: form.category.trim() || null,
      currency: form.currency.trim().toUpperCase(),
      version: form.version.trim(),
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

function readRate(value: string, label: string): NumberFieldResult {
  const number = Number(value)
  if (!Number.isFinite(number)) return { error: `${label} must be a number.` }
  if (number < 0 || number > 100) return { error: `${label} must be between 0 and 100.` }
  return { value: number }
}

function readMoney(value: string, label: string): NumberFieldResult {
  const number = Number(value || 0)
  if (!Number.isFinite(number)) return { error: `${label} must be a number.` }
  if (number < 0) return { error: `${label} must be zero or positive.` }
  return { value: number }
}

function buildNextVersion(policies: MarketplaceFeePolicy[]) {
  const maxVersion = policies.reduce((max, policy) => {
    const match = /^v(\d+)$/i.exec(policy.version)
    return match ? Math.max(max, Number(match[1])) : max
  }, 0)
  return `v${Math.max(1, maxVersion + 1)}`
}

function rateToPercent(rate: number) {
  return String(Number((rate * 100).toFixed(3)))
}

function totalFixedCosts(policy: MarketplaceFeePolicy) {
  return (
    policy.fixedPerOrderFee +
    policy.fixedPerUnitFee +
    policy.fulfilmentFee +
    policy.shippingSubsidy +
    policy.otherVariableCost
  )
}

function policyErrorMessage(error: unknown) {
  if (!error) return null
  if (axios.isAxiosError(error)) {
    const status = error.response?.status
    if (status === 401 || status === 403) return "You are not authorized to update pricing policies."
    if (status === 404) return "Product or fee policy not found."
    if (status === 400 || status === 422) return getErrorMessage(error, "Please check the fee policy values.")
  }
  return "Could not save marketplace fee policy. Please try again."
}
