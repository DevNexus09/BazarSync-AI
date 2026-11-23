import { Link, useNavigate } from "react-router-dom"
import { AlertTriangle, CheckCircle2, ChevronRight, Pencil, Trash2 } from "lucide-react"

import type { Product } from "@/types/product"
import { Button } from "@/components/ui/button"
import { TONE_CLASSES, type StatusTone } from "@/components/ui/status"
import { formatCurrency, formatNumber, formatPercent } from "@/utils/formatters"
import { cn } from "@/lib/utils"
import { getActualMargin } from "@/utils/product"

type ProductListProps = {
  products: Product[]
  onDelete: (productId: string) => void
  deletingId?: string | null
}

const PRODUCT_STATUS_TONE: Record<NonNullable<Product["status"]>, StatusTone> = {
  ACTIVE: "success",
  DRAFT: "info",
  INACTIVE: "warning",
  ARCHIVED: "neutral",
  DISCONTINUED: "neutral",
}

export function ProductStatusBadge({ status }: { status?: Product["status"] }) {
  const value = status ?? "ACTIVE"
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        TONE_CLASSES[PRODUCT_STATUS_TONE[value] ?? "neutral"]
      )}
    >
      {value.charAt(0) + value.slice(1).toLowerCase()}
    </span>
  )
}

export function MarginPill({ product }: { product: Product }) {
  const margin = getActualMargin(product)
  const ok = margin >= product.minimumMargin
  const Icon = ok ? CheckCircle2 : AlertTriangle
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        TONE_CLASSES[ok ? "success" : "danger"]
      )}
      title={`Minimum margin ${formatPercent(product.minimumMargin)}`}
    >
      <Icon aria-hidden className="size-3.5" />
      {formatPercent(margin)}
    </span>
  )
}

export function ProductAvatar({ title, className }: { title: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex size-10 shrink-0 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-sm font-semibold uppercase text-primary",
        className
      )}
    >
      {title.trim().charAt(0) || "?"}
    </span>
  )
}

function StockCell({ quantity }: { quantity: number }) {
  if (quantity <= 0) {
    return <span className="text-xs font-medium text-danger">Out of stock</span>
  }
  return <span className="tabular-nums text-foreground">{formatNumber(quantity)}</span>
}

function RowActions({
  product,
  onDelete,
  deleting,
}: {
  product: Product
  onDelete: (productId: string) => void
  deleting: boolean
}) {
  return (
    <div className="flex justify-end gap-1" onClick={(event) => event.stopPropagation()}>
      <Button variant="ghost" size="icon" asChild>
        <Link to={`/app/products/${product.id}/edit`} aria-label={`Edit ${product.title}`}>
          <Pencil className="size-4" />
        </Link>
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="text-muted-foreground hover:text-danger"
        onClick={() => onDelete(product.id)}
        disabled={deleting}
        aria-label={`Delete ${product.title}`}
      >
        <Trash2 className="size-4" />
      </Button>
    </div>
  )
}

export function ProductList({ products, onDelete, deletingId }: ProductListProps) {
  const navigate = useNavigate()

  return (
    <>
      <div className="hidden md:block">
        <table className="w-full text-sm">
          <thead className="border-b border-border/60 text-left text-xs font-medium text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-medium">Product</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 text-right font-medium">Price</th>
              <th className="px-4 py-3 font-medium">Margin</th>
              <th className="px-4 py-3 text-right font-medium">Stock</th>
              <th className="px-4 py-3 text-right font-medium">Lead time</th>
              <th className="w-24 px-4 py-3">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {products.map((product) => (
              <tr
                key={product.id}
                onClick={() => navigate(`/app/products/${product.id}`)}
                className={cn(
                  "cursor-pointer border-b border-border/40 transition-colors last:border-0 hover:bg-muted/30",
                  deletingId === product.id && "opacity-50"
                )}
              >
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    <ProductAvatar title={product.title} />
                    <div className="min-w-0">
                      <Link
                        to={`/app/products/${product.id}`}
                        onClick={(event) => event.stopPropagation()}
                        className="block truncate font-medium text-foreground hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        {product.title}
                      </Link>
                      <p className="truncate text-xs text-muted-foreground">
                        {[product.sku, product.category || "Uncategorized"].filter(Boolean).join(" · ")}
                      </p>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <ProductStatusBadge status={product.status} />
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="font-medium tabular-nums text-foreground">
                    {formatCurrency(product.sellingPrice)}
                  </div>
                  <div className="text-xs tabular-nums text-muted-foreground">
                    Cost {formatCurrency(product.costPrice)}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <MarginPill product={product} />
                </td>
                <td className="px-4 py-3 text-right">
                  <StockCell quantity={product.stockQuantity} />
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                  {formatNumber(product.supplierLeadTime)}d
                </td>
                <td className="px-4 py-3">
                  <RowActions product={product} onDelete={onDelete} deleting={deletingId === product.id} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="divide-y divide-border/40 md:hidden">
        {products.map((product) => (
          <li key={product.id} className={cn(deletingId === product.id && "opacity-50")}>
            <Link
              to={`/app/products/${product.id}`}
              className="flex items-center gap-3 p-4 transition-colors hover:bg-muted/30"
            >
              <ProductAvatar title={product.title} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate font-medium text-foreground">{product.title}</p>
                  <ProductStatusBadge status={product.status} />
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">
                    {formatCurrency(product.sellingPrice)}
                  </span>
                  <MarginPill product={product} />
                  <span>
                    {product.stockQuantity > 0
                      ? `${formatNumber(product.stockQuantity)} in stock`
                      : "Out of stock"}
                  </span>
                </div>
              </div>
              <ChevronRight aria-hidden className="size-4 text-muted-foreground" />
            </Link>
          </li>
        ))}
      </ul>
    </>
  )
}
