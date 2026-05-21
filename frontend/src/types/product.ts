export type Product = {
  id: string
  sellerId?: string
  title: string
  description: string
  category: string
  specifications: Record<string, string>
  searchableText?: string | null
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
  description: string
  category: string
  specifications: Record<string, string>
  costPrice: number
  sellingPrice: number
  stockQuantity: number
  supplierLeadTime: number
  minimumMargin: number
}
