import { useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { deadStockKeys } from "@/hooks/useDeadStock"
import { useProducts } from "@/hooks/use-products"
import { importSalesRecord, type SalesImportInput } from "@/services/phase9-setup-service"

const statuses: SalesImportInput["status"][] = ["COMPLETED", "FULFILLED", "PENDING", "CANCELLED", "FAILED_PAYMENT"]

export default function SalesImportPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const products = useProducts().data ?? []
  const [productId, setProductId] = useState(params.get("productId") ?? "")
  const [quantity, setQuantity] = useState("1")
  const [soldAt, setSoldAt] = useState(new Date().toISOString().slice(0, 16))
  const [status, setStatus] = useState<SalesImportInput["status"]>("COMPLETED")
  const [unitPrice, setUnitPrice] = useState("")
  const [currency, setCurrency] = useState("BDT")
  const [sourceReference, setSourceReference] = useState("manual-sale-001")
  const [isTestOrder, setIsTestOrder] = useState(false)
  const mutation = useMutation({
    mutationFn: () =>
      importSalesRecord({
        productId,
        quantity: Number(quantity),
        soldAt: new Date(soldAt).toISOString(),
        status,
        unitPrice: unitPrice ? Number(unitPrice) : null,
        currency,
        sourceReference,
        isTestOrder,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: deadStockKeys.all })
    },
  })
  const canSubmit = productId && Number(quantity) > 0 && soldAt && sourceReference
  const counts = status === "COMPLETED" || status === "FULFILLED"
  return (
    <div className="space-y-6">
      <PageHeader title="Import sales record" description="Only COMPLETED and FULFILLED sales are used for dead stock and velocity calculations. Pending, cancelled, failed-payment, and test orders are excluded." />
      <div className="glass-panel max-w-2xl space-y-4 p-4">
        {mutation.isSuccess ? <p className="rounded-lg border border-emerald-400/40 bg-emerald-400/10 p-3 text-sm text-emerald-100">Sales record imported. Run dead stock analysis to refresh last sale and velocity.</p> : null}
        {mutation.isError ? <p className="rounded-lg border border-red-400/40 bg-red-400/10 p-3 text-sm text-red-100">Could not import sales record. Check product, date, and source reference.</p> : null}
        <ProductSelect products={products} value={productId} onChange={setProductId} />
        <Field label="Quantity" type="number" value={quantity} onChange={setQuantity} />
        <Field label="Sold date" type="datetime-local" value={soldAt} onChange={setSoldAt} />
        <label className="flex flex-col gap-1 text-sm text-muted-foreground">Status
          <select className="h-10 rounded-lg border border-border bg-background px-3 text-foreground" value={status} onChange={(event) => setStatus(event.target.value as SalesImportInput["status"])}>
            {statuses.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <p className={counts && !isTestOrder ? "text-sm text-emerald-200" : "text-sm text-amber-200"}>
          {counts && !isTestOrder ? "This record will count toward last sale and velocity." : "This record will be stored but excluded from Phase 6 and Phase 9 calculations."}
        </p>
        <Field label="Unit price" type="number" value={unitPrice} onChange={setUnitPrice} />
        <Field label="Currency" value={currency} onChange={setCurrency} />
        <Field label="Source reference" value={sourceReference} onChange={setSourceReference} />
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={isTestOrder} onChange={(event) => setIsTestOrder(event.target.checked)} />
          Test order
        </label>
        <div className="flex gap-2">
          <Button disabled={!canSubmit || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? "Importing..." : "Import sale"}</Button>
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
