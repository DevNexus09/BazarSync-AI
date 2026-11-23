import axios from "axios"
import { ArrowLeft, CheckCircle2, CircleAlert, Save } from "lucide-react"
import { useMemo, useState } from "react"
import type { FormEvent } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { InlineAlert } from "@/components/common/inline-alert"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  createMarketplaceFeePolicy,
  getEffectiveMarketplaceFeePolicy,
  type MarketplaceFeePolicyInput,
} from "@/services/pricing-policy-service"
import { getErrorMessage } from "@/utils/errors"
import {
  buildMarketplaceFeePayload,
  type FeeFormState,
} from "@/utils/marketplace-fee-setup"

const today = () => new Date().toISOString().slice(0, 10)

export default function MarketplaceFeeSetupPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form, setForm] = useState<FeeFormState>(() => ({
    productId: searchParams.get("productId") ?? "",
    marketplace: searchParams.get("marketplace") ?? "Daraz Bangladesh",
    category: searchParams.get("category") ?? "",
    currency: searchParams.get("currency") ?? "BDT",
    commissionRatePercent: "",
    paymentFeeRatePercent: "",
    fixedPerOrderFee: "0",
    fixedPerUnitFee: "0",
    fulfilmentFee: "0",
    shippingSubsidy: "0",
    otherVariableCost: "0",
    effectiveFrom: today(),
  }))
  const [validationError, setValidationError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [verificationMessage, setVerificationMessage] = useState<string | null>(null)
  const [verificationWarning, setVerificationWarning] = useState<string | null>(null)

  const productId = form.productId.trim()
  const returnPath = useMemo(() => {
    const params = new URLSearchParams()
    if (productId) params.set("productId", productId)
    const query = params.toString()
    return `/app/pricing${query ? `?${query}` : ""}`
  }, [productId])

  const mutation = useMutation({
    mutationFn: async (payload: MarketplaceFeePolicyInput) => {
      const saved = await createMarketplaceFeePolicy(payload)
      if (!payload.productId) {
        return { saved, verified: false as const }
      }

      try {
        const effectiveFee = await getEffectiveMarketplaceFeePolicy({
          productId: payload.productId,
          marketplace: payload.marketplace,
        })
        return {
          saved,
          verified: Boolean(effectiveFee.id) && !effectiveFee.isDefault,
        }
      } catch {
        return { saved, verified: false as const }
      }
    },
    onSuccess: async (result) => {
      setSuccessMessage("Marketplace fee policy saved successfully.")
      if (result.verified) {
        setVerificationMessage("Fee setup verified. You can now run pricing simulation.")
        setVerificationWarning(null)
      } else if (productId) {
        setVerificationMessage(null)
        setVerificationWarning(
          "Saved, but effective fee lookup could not be verified. Please check marketplace/category settings."
        )
      }
      await queryClient.invalidateQueries({ queryKey: ["pricing"] })
      window.setTimeout(() => navigate(returnPath), 1200)
    },
  })

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setValidationError(null)
    setSuccessMessage(null)
    setVerificationMessage(null)
    setVerificationWarning(null)

    const payload = buildMarketplaceFeePayload(form)
    if ("error" in payload) {
      setValidationError(payload.error)
      return
    }

    mutation.mutate(payload.value)
  }

  const saveError = mutation.error ? marketplaceFeeErrorMessage(mutation.error) : null

  return (
    <div className="space-y-6">
      <PageHeader
        title="Marketplace fee setup"
        description="Add the selling costs needed for safe revenue and profit simulation."
        action={
          <Button asChild variant="outline">
            <Link to={returnPath}>
              <ArrowLeft className="size-4" aria-hidden="true" />
              Back to Pricing Analytics
            </Link>
          </Button>
        }
      />

      <form
        onSubmit={submit}
        className="rounded-xl border border-border/70 bg-card p-4 shadow-sm"
      >
        <div className="grid gap-4 lg:grid-cols-3">
          <Field
            label="Marketplace"
            helper="The marketplace where this fee policy applies."
            value={form.marketplace}
            onChange={(value) => setForm((current) => ({ ...current, marketplace: value }))}
            required
          />
          <Field
            label="Category"
            helper="Optional product category for category-specific fees."
            value={form.category}
            onChange={(value) => setForm((current) => ({ ...current, category: value }))}
          />
          <Field
            label="Currency"
            helper="Currency used for this marketplace."
            value={form.currency}
            onChange={(value) => setForm((current) => ({ ...current, currency: value.toUpperCase() }))}
            required
          />
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Field
            label="Commission rate"
            helper="Marketplace commission charged on selling price."
            value={form.commissionRatePercent}
            onChange={(value) => setForm((current) => ({ ...current, commissionRatePercent: value }))}
            type="number"
            suffix="%"
            placeholder="8"
            required
          />
          <Field
            label="Payment fee rate"
            helper="Payment processing fee charged on selling price."
            value={form.paymentFeeRatePercent}
            onChange={(value) => setForm((current) => ({ ...current, paymentFeeRatePercent: value }))}
            type="number"
            suffix="%"
            placeholder="2.5"
            required
          />
          <Field
            label="Fixed per order fee"
            helper="Fixed amount charged for each order."
            value={form.fixedPerOrderFee}
            onChange={(value) => setForm((current) => ({ ...current, fixedPerOrderFee: value }))}
            type="number"
          />
          <Field
            label="Fixed per unit fee"
            helper="Fixed amount charged for each unit sold."
            value={form.fixedPerUnitFee}
            onChange={(value) => setForm((current) => ({ ...current, fixedPerUnitFee: value }))}
            type="number"
          />
          <Field
            label="Fulfilment fee"
            helper="Packing, warehouse, or fulfilment cost charged by marketplace."
            value={form.fulfilmentFee}
            onChange={(value) => setForm((current) => ({ ...current, fulfilmentFee: value }))}
            type="number"
          />
          <Field
            label="Shipping subsidy"
            helper="Seller-paid shipping or free delivery support."
            value={form.shippingSubsidy}
            onChange={(value) => setForm((current) => ({ ...current, shippingSubsidy: value }))}
            type="number"
          />
          <Field
            label="Other variable cost"
            helper="Any other selling cost per order or unit."
            value={form.otherVariableCost}
            onChange={(value) => setForm((current) => ({ ...current, otherVariableCost: value }))}
            type="number"
          />
          <Field
            label="Effective from date"
            helper="The date this fee policy starts applying."
            value={form.effectiveFrom}
            onChange={(value) => setForm((current) => ({ ...current, effectiveFrom: value }))}
            type="date"
            required
          />
        </div>

        <div className="mt-5 space-y-3">
          {validationError ? <InlineAlert variant="error" message={validationError} /> : null}
          {saveError ? <InlineAlert variant="error" message={saveError} /> : null}
          {successMessage ? (
            <InlineAlert variant="success" message={successMessage} />
          ) : null}
          {verificationMessage ? (
            <InlineAlert variant="success" message={verificationMessage} />
          ) : null}
          {verificationWarning ? (
            <InlineAlert variant="info" message={verificationWarning} />
          ) : null}
        </div>

        <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="inline-flex items-start gap-2 text-sm text-muted-foreground">
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            Percent fields are saved as decimal rates. For example, 8% is saved as 0.08.
          </p>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? (
              "Saving..."
            ) : (
              <>
                <Save className="size-4" aria-hidden="true" />
                Save Fee Policy
              </>
            )}
          </Button>
        </div>
      </form>

      {successMessage ? (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-success">
          <div className="flex items-center gap-2 font-semibold">
            <CheckCircle2 className="size-4" aria-hidden="true" />
            Returning to Pricing Analytics...
          </div>
        </div>
      ) : null}
    </div>
  )
}

function Field({
  label,
  helper,
  value,
  onChange,
  type = "text",
  suffix,
  placeholder,
  required,
}: {
  label: string
  helper: string
  value: string
  onChange: (value: string) => void
  type?: "text" | "number" | "date"
  suffix?: string
  placeholder?: string
  required?: boolean
}) {
  const id = label.toLowerCase().replaceAll(" ", "-")
  return (
    <div className="space-y-2">
      <label
        htmlFor={id}
        className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
      >
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
          placeholder={placeholder}
          required={required}
          className={suffix ? "pr-10" : undefined}
        />
        {suffix ? (
          <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-muted-foreground">
            {suffix}
          </span>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">{helper}</p>
    </div>
  )
}

function marketplaceFeeErrorMessage(error: unknown) {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status
    if (status === 401 || status === 403) {
      return "You are not authorized to update pricing policies."
    }
    if (status === 404) {
      return "Product not found or you do not have access to it."
    }
    if (status === 422 || status === 400) {
      return getErrorMessage(error, "Please check the fee policy values.")
    }
  }
  return "Could not save marketplace fee policy. Please try again."
}
