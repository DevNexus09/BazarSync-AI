import { Link } from "react-router-dom"

import type { Product } from "@/types/product"
import { Button } from "@/components/ui/button"
import { formatCurrency, formatNumber, formatPercent } from "@/utils/formatters"
import { cn } from "@/lib/utils"

type ProductListProps = {
  products: Product[]
  onDelete: (productId: string) => void
  deletingId?: string | null
}

function getActualMargin(product: Product) {
  if (product.sellingPrice <= 0) {
    return 0
  }

  return ((product.sellingPrice - product.costPrice) / product.sellingPrice) * 100
}

export function ProductList({ products, onDelete, deletingId }: ProductListProps) {
  return (
    <div className="space-y-4">
      <div className="hidden overflow-hidden rounded-xl border bg-background shadow-sm md:block">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Product</th>
              <th className="px-4 py-3">Cost</th>
              <th className="px-4 py-3">Selling</th>
              <th className="px-4 py-3">Margin</th>
              <th className="px-4 py-3">Stock</th>
              <th className="px-4 py-3">Lead time</th>
              <th className="px-4 py-3">Min margin</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {products.map((product) => {
              const actualMargin = getActualMargin(product)
              const meetsMargin = actualMargin >= product.minimumMargin
              return (
                <tr key={product.id} className="border-b last:border-0">
                  <td className="px-4 py-3 font-medium text-foreground">
                    {product.title}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatCurrency(product.costPrice)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatCurrency(product.sellingPrice)}
                  </td>
                  <td
                    className={cn(
                      "px-4 py-3 font-medium",
                      meetsMargin ? "text-emerald-600" : "text-rose-600"
                    )}
                  >
                    {formatPercent(actualMargin)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatNumber(product.stockQuantity)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatNumber(product.supplierLeadTime)} days
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatPercent(product.minimumMargin)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <Button variant="outline" size="sm" asChild>
                        <Link to={`/app/products/${product.id}`}>Details</Link>
                      </Button>
                      <Button variant="outline" size="sm" asChild>
                        <Link to={`/app/products/${product.id}/edit`}>Edit</Link>
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => onDelete(product.id)}
                        disabled={deletingId === product.id}
                      >
                        {deletingId === product.id ? "Deleting..." : "Delete"}
                      </Button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 md:hidden">
        {products.map((product) => {
          const actualMargin = getActualMargin(product)
          const meetsMargin = actualMargin >= product.minimumMargin
          return (
            <div key={product.id} className="rounded-xl border bg-background p-4 shadow-sm">
              <div className="text-sm font-semibold text-foreground">
                {product.title}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3 text-sm text-muted-foreground">
                <div>
                  <p className="text-xs uppercase tracking-wide">Cost</p>
                  <p className="font-medium text-foreground">
                    {formatCurrency(product.costPrice)}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide">Selling</p>
                  <p className="font-medium text-foreground">
                    {formatCurrency(product.sellingPrice)}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide">Margin</p>
                  <p
                    className={cn(
                      "font-medium",
                      meetsMargin ? "text-emerald-600" : "text-rose-600"
                    )}
                  >
                    {formatPercent(actualMargin)}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide">Stock</p>
                  <p className="font-medium text-foreground">
                    {formatNumber(product.stockQuantity)}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide">Lead time</p>
                  <p className="font-medium text-foreground">
                    {formatNumber(product.supplierLeadTime)} days
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide">Min margin</p>
                  <p className="font-medium text-foreground">
                    {formatPercent(product.minimumMargin)}
                  </p>
                </div>
              </div>
              <div className="mt-4 flex gap-2">
                <Button variant="outline" size="sm" asChild>
                  <Link to={`/app/products/${product.id}`}>Details</Link>
                </Button>
                <Button variant="outline" size="sm" asChild>
                  <Link to={`/app/products/${product.id}/edit`}>Edit</Link>
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => onDelete(product.id)}
                  disabled={deletingId === product.id}
                >
                  {deletingId === product.id ? "Deleting..." : "Delete"}
                </Button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
