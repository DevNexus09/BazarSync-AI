import { useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { deadStockKeys } from "@/hooks/useDeadStock"
import { useProducts } from "@/hooks/use-products"
import { createPricingPolicy } from "@/services/phase9-setup-service"

export default function PricingPolicySetupPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const products = useProducts().data ?? []
  const [productId, setProductId] = useState(params.get("productId") ?? "")
  const [marketplace, setMarketplace] = useState("DARAZ")
  const [currency, setCurrency] = useState("BDT")
  const [minimumMarginPercent, setMinimumMarginPercent] = useState("15")
  const [minimumUnitProfit, setMinimumUnitProfit] = useState("0")
  const [maximumDiscountPercent, setMaximumDiscountPercent] = useState("20")
  const [maximumPriceIncreasePercent, setMaximumPriceIncreasePercent] = useState("10")
  const [minimumAllowedPrice, setMinimumAllowedPrice] = useState("")
  const [maximumAllowedPrice, setMaximumAllowedPrice] = useState("")
  const [priceIncrement, setPriceIncrement] = useState("1")
  const [objective, setObjective] = useState("MAXIMIZE_EXPECTED_PROFIT")
  const [effectiveFrom, setEffectiveFrom] = useState(new Date().toISOString().slice(0, 10))
  const mutation = useMutation({
    mutationFn: () =>
      createPricingPolicy({
        productId,
        marketplace,
        currency,
        minimumMarginPercent: Number(minimumMarginPercent),
        minimumUnitProfit: Number(minimumUnitProfit),
        maximumDiscountPercent: Number(maximumDiscountPercent),
        maximumPriceIncreasePercent: Number(maximumPriceIncreasePercent),
        minimumAllowedPrice: minimumAllowedPrice ? Number(minimumAllowedPrice) : null,
        maximumAllowedPrice: maximumAllowedPrice ? Number(maximumAllowedPrice) : null,
        priceIncrement: Number(priceIncrement),
        objective,
        effectiveFrom: new Date(`${effectiveFrom}T00:00:00`).toISOString(),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["pricing"] })
      await queryClient.invalidateQueries({ queryKey: deadStockKeys.all })
    },
  })
  const canSubmit = productId && Number(priceIncrement) > 0 && effectiveFrom
  return (
    <div className="space-y-6">
      <PageHeader title="Pricing policy setup" description="Define minimum margin, discount limits, and price increments so MarginGuard can evaluate recovery pricing safely." />
      <div className="glass-panel max-w-2xl space-y-4 p-4">
        {mutation.isSuccess ? <p className="rounded-lg border border-emerald-400/40 bg-emerald-400/10 p-3 text-sm text-emerald-100">Pricing policy saved. Run dead stock analysis to refresh recommendations.</p> : null}
        {mutation.isError ? <p className="rounded-lg border border-red-400/40 bg-red-400/10 p-3 text-sm text-red-100">Could not save pricing policy. Please check rates and price bounds.</p> : null}
        <ProductSelect products={products} value={productId} onChange={setProductId} />
        <Field label="Marketplace" value={marketplace} onChange={setMarketplace} />
        <Field label="Currency" value={currency} onChange={setCurrency} />
        <Field label="Minimum margin %" type="number" value={minimumMarginPercent} onChange={setMinimumMarginPercent} />
        <Field label="Minimum unit profit" type="number" value={minimumUnitProfit} onChange={setMinimumUnitProfit} />
        <Field label="Maximum discount %" type="number" value={maximumDiscountPercent} onChange={setMaximumDiscountPercent} />
        <Field label="Maximum price increase %" type="number" value={maximumPriceIncreasePercent} onChange={setMaximumPriceIncreasePercent} />
        <Field label="Minimum allowed price" type="number" value={minimumAllowedPrice} onChange={setMinimumAllowedPrice} />
        <Field label="Maximum allowed price" type="number" value={maximumAllowedPrice} onChange={setMaximumAllowedPrice} />
        <Field label="Price increment" type="number" value={priceIncrement} onChange={setPriceIncrement} />
        <label className="flex flex-col gap-1 text-sm text-muted-foreground">Objective
          <select className="h-10 rounded-lg border border-border bg-background px-3 text-foreground" value={objective} onChange={(event) => setObjective(event.target.value)}>
            <option value="MAXIMIZE_EXPECTED_PROFIT">Maximize expected profit</option>
            <option value="MAXIMIZE_REVENUE_WITH_MARGIN_FLOOR">Maximize revenue with margin floor</option>
            <option value="PROTECT_INVENTORY">Protect inventory</option>
            <option value="CLEAR_EXCESS_STOCK">Clear excess stock</option>
          </select>
        </label>
        <Field label="Effective from" type="date" value={effectiveFrom} onChange={setEffectiveFrom} />
        <div className="flex gap-2">
          <Button disabled={!canSubmit || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? "Saving..." : "Save pricing policy"}</Button>
          <Button variant="outline" onClick={() => navigate("/app/inventory-intelligence")}>Back to dashboard</Button>
        </div>
      </div>
    </div>
  )
}

function ProductSelect({ products, value, onChange }: { products: { id: string; title: string }[]; value: string; onChange: (value: string) => void }) {
  return <label className="flex flex-col gap-1 text-sm text-muted-foreground">Product<select className="h-10 rounded-lg border border-border bg-background px-3 text-foreground" value={value} onChange={(event) => onChange(event.target.value)}><option value="">Select product</option>{products.map((product) => <option key={product.id} value={product.id}>{product.title}</option>)}</select></label>
}

function Field({ label, value, onChange, type = "text" }: { label: string; value: string; onChange: (value: string) => void; type?: string }) {
  return <label className="flex flex-col gap-1 text-sm text-muted-foreground">{label}<input className="h-10 rounded-lg border border-border bg-background px-3 text-foreground" type={type} value={value} onChange={(event) => onChange(event.target.value)} /></label>
}
