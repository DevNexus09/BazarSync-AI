import type { Product } from "@/types/product"

export function getActualMargin(product: Pick<Product, "sellingPrice" | "costPrice">) {
  if (product.sellingPrice <= 0) {
    return 0
  }

  return ((product.sellingPrice - product.costPrice) / product.sellingPrice) * 100
}
