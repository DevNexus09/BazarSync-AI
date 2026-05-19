export type Product = {
  id: string
  sellerId?: string
  title: string
  costPrice: number
  sellingPrice: number
  stockQuantity: number
  supplierLeadTime: number
  minimumMargin: number
  pricingWarning?: string | null
  createdAt?: string
  updatedAt?: string
}

export type ProductInput = {
  title: string
  costPrice: number
  sellingPrice: number
  stockQuantity: number
  supplierLeadTime: number
  minimumMargin: number
}
