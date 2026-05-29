import { useMemo, useState } from "react"
import { ChevronDown, PackageSearch } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import type { Product } from "@/types/product"
import { formatCurrency, formatNumber } from "@/utils/formatters"

type ProductSelectorProps = {
  products?: Product[]
  value?: string | null
  onChange: (productId: string | null) => void
  isLoading?: boolean
  isError?: boolean
  disabled?: boolean
}

export function ProductSelector({
  products,
  value,
  onChange,
  isLoading = false,
  isError = false,
  disabled = false,
}: ProductSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [query, setQuery] = useState("")
  const selected = products?.find((item) => item.id === value) ?? null

  const filtered = useMemo(() => {
    if (!products) {
      return []
    }
    const trimmed = query.trim().toLowerCase()
    if (!trimmed) {
      return products
    }
    return products.filter((product) =>
      product.title.toLowerCase().includes(trimmed)
    )
  }, [products, query])

  const handleSelect = (productId: string) => {
    onChange(productId)
    setIsOpen(false)
  }

  const emptyLabel =
    products && products.length === 0
      ? "No products found. Add a product first."
      : "No matches found."

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs font-semibold text-muted-foreground">
        <span>Product selector</span>
        {selected ? (
          <span className="text-[10px] uppercase text-emerald-600">Selected</span>
        ) : null}
      </div>
      <div className="relative">
        <Button
          type="button"
          variant="outline"
          className={cn(
<<<<<<< HEAD
            "h-auto w-full items-start justify-between gap-3 border-border/60 bg-card/60 px-3 py-3 text-left",
=======
            "h-auto w-full items-start justify-between gap-3 border-dashed px-3 py-3 text-left",
>>>>>>> develop
            disabled && "cursor-not-allowed opacity-60"
          )}
          disabled={disabled}
          onClick={() => setIsOpen((open) => !open)}
          aria-expanded={isOpen}
        >
          <div className="space-y-1">
            <p className="text-sm font-semibold text-foreground">
              {selected ? selected.title : "Select a product"}
            </p>
            <p className="text-xs text-muted-foreground">
              {selected
                ? `${formatCurrency(selected.sellingPrice)} • ${formatNumber(
                    selected.stockQuantity
                  )} in stock`
                : "Pick a product to preview and send a snapshot."}
            </p>
          </div>
          <ChevronDown className="mt-1 size-4 text-muted-foreground" />
        </Button>

        {isOpen ? (
<<<<<<< HEAD
          <div className="absolute z-10 mt-2 w-full overflow-hidden rounded-xl border border-border/60 bg-card/90 shadow-[0_0_0_1px_rgba(59,130,246,0.15),_0_24px_60px_rgba(4,8,16,0.6)]">
            <div className="border-b border-border/60 px-3 py-2">
=======
          <div className="absolute z-10 mt-2 w-full overflow-hidden rounded-xl border bg-background shadow-lg">
            <div className="border-b px-3 py-2">
>>>>>>> develop
              <Input
                placeholder="Search products"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                disabled={disabled || isLoading}
              />
            </div>
            <div className="max-h-64 overflow-y-auto">
              {isLoading ? (
                <div className="space-y-3 px-3 py-3">
                  {[0, 1, 2].map((item) => (
                    <div
                      key={item}
                      className="h-10 animate-pulse rounded-lg bg-muted/40"
                    />
                  ))}
                </div>
              ) : isError ? (
                <div className="px-3 py-4 text-xs text-rose-600">
                  Unable to load products right now.
                </div>
              ) : filtered.length === 0 ? (
                <div className="flex flex-col items-center gap-2 px-3 py-6 text-xs text-muted-foreground">
                  <PackageSearch className="size-4" />
                  <span>{emptyLabel}</span>
                </div>
              ) : (
<<<<<<< HEAD
                <div className="divide-y divide-border/60">
=======
                <div className="divide-y">
>>>>>>> develop
                  {filtered.map((product) => (
                    <button
                      key={product.id}
                      type="button"
                      onClick={() => handleSelect(product.id)}
                      className="flex w-full items-center justify-between px-3 py-2 text-left text-xs hover:bg-muted/40"
                    >
                      <div>
                        <p className="text-sm font-semibold text-foreground">
                          {product.title}
                        </p>
                        <p className="text-[11px] text-muted-foreground">
                          {formatCurrency(product.sellingPrice)} •{" "}
                          {formatNumber(product.stockQuantity)} in stock
                        </p>
                      </div>
                      <span className="text-[11px] text-muted-foreground">
                        {product.supplierLeadTime}d lead
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null}
      </div>
      {!isOpen && isError ? (
        <p className="text-xs text-rose-600">
          Unable to load products right now.
        </p>
      ) : null}
    </div>
  )
}
