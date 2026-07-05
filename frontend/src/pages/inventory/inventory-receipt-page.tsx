import { useState } from "react"
import type { ReactNode } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { deadStockKeys } from "@/hooks/useDeadStock"
import { useProducts } from "@/hooks/use-products"
import { createInventoryStockIn } from "@/services/phase9-setup-service"

export default function InventoryReceiptPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const products = useProducts().data ?? []
  const [productId, setProductId] = useState(params.get("productId") ?? "")
  const [quantity, setQuantity] = useState("1")
  const [receivedAt, setReceivedAt] = useState(new Date().toISOString().slice(0, 10))
  const [unitCost, setUnitCost] = useState("")
  const [currency, setCurrency] = useState("BDT")
  const [sourceReference, setSourceReference] = useState("manual-initial-stock")
  const [notes, setNotes] = useState("")
  const mutation = useMutation({
    mutationFn: () =>
      createInventoryStockIn({
        productId,
        quantity: Number(quantity),
        receivedAt: new Date(`${receivedAt}T00:00:00`).toISOString(),
        unitCost: unitCost ? Number(unitCost) : null,
        currency,
        sourceReference,
        notes,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: deadStockKeys.all })
    },
  })
  const canSubmit = productId && Number(quantity) > 0 && receivedAt
  return (
    <div className="space-y-6">
      <PageHeader title="Add inventory receipt" description="Record when stock entered inventory. This date is used to calculate inventory age for dead stock detection." />
      <SetupPanel message={mutation.isSuccess ? "Inventory receipt saved. Run dead stock analysis to refresh Phase 9 calculations." : null} error={mutation.error}>
        <ProductField products={products} value={productId} onChange={setProductId} />
        <Field label="Quantity" type="number" value={quantity} onChange={setQuantity} />
        <Field label="Received date" type="date" value={receivedAt} onChange={setReceivedAt} />
        <Field label="Unit cost, optional" type="number" value={unitCost} onChange={setUnitCost} />
        <Field label="Currency" value={currency} onChange={setCurrency} />
        <Field label="Source reference" value={sourceReference} onChange={setSourceReference} />
        <label className="flex flex-col gap-1 text-sm text-muted-foreground">
          Notes
          <textarea className="min-h-24 rounded-lg border border-border bg-background px-3 py-2 text-foreground" value={notes} onChange={(event) => setNotes(event.target.value)} />
        </label>
        <div className="flex gap-2">
          <Button disabled={!canSubmit || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? "Saving..." : "Save receipt"}</Button>
          <Button variant="outline" onClick={() => navigate("/app/inventory-intelligence")}>Back to dashboard</Button>
        </div>
      </SetupPanel>
    </div>
  )
}

function ProductField({ products, value, onChange }: { products: { id: string; title: string }[]; value: string; onChange: (value: string) => void }) {
  return (
    <label className="flex flex-col gap-1 text-sm text-muted-foreground">Product
      <select className="h-10 rounded-lg border border-border bg-background px-3 text-foreground" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Select product</option>
        {products.map((product) => <option key={product.id} value={product.id}>{product.title}</option>)}
      </select>
    </label>
  )
}

function Field({ label, value, onChange, type = "text" }: { label: string; value: string; onChange: (value: string) => void; type?: string }) {
  return <label className="flex flex-col gap-1 text-sm text-muted-foreground">{label}<input className="h-10 rounded-lg border border-border bg-background px-3 text-foreground" type={type} value={value} onChange={(event) => onChange(event.target.value)} /></label>
}

function SetupPanel({ children, message, error }: { children: ReactNode; message: string | null; error: unknown }) {
  return <div className="glass-panel max-w-2xl space-y-4 p-4">{message ? <p className="rounded-lg border border-emerald-400/40 bg-emerald-400/10 p-3 text-sm text-emerald-100">{message}</p> : null}{error ? <p className="rounded-lg border border-red-400/40 bg-red-400/10 p-3 text-sm text-red-100">Could not save setup data. Please check the values.</p> : null}{children}</div>
}
