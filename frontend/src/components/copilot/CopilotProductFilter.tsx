import { Package } from "lucide-react"

import { useProducts } from "@/hooks/use-products"

export function CopilotProductFilter({
  value,
  onChange,
}: {
  value: string | null
  onChange: (productId: string | null) => void
}) {
  const products = useProducts()

  return (
    <label className="flex items-center gap-2 rounded-lg border border-border/60 bg-muted/20 px-2 py-1.5 text-xs text-muted-foreground">
      <Package className="size-3.5 shrink-0" aria-hidden="true" />
      <span className="sr-only">Product filter</span>
      <select
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
        className="min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none"
        aria-label="Product filter"
      >
        <option value="">All products</option>
        {(products.data ?? []).map((product) => (
          <option key={product.id} value={product.id}>
            {product.title}
          </option>
        ))}
      </select>
    </label>
  )
}

